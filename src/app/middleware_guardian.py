"""Pure ASGI Middleware для добавления guardian_meta во все JSON-ответы."""
import json
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.requests import Request

class GuardianASGIMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        content_type = ""
        response_body = bytearray()
        initial_message = None

        async def send_wrapper(message):
            nonlocal content_type, initial_message, response_body

            if message["type"] == "http.response.start":
                initial_message = message
                headers = dict(
                    (k.decode(), v.decode())
                    for k, v in message.get("headers", [])
                )
                content_type = headers.get("content-type", "")
                return

            if message["type"] == "http.response.body":
                body_chunk = message.get("body", b"")
                more_body = message.get("more_body", False)
                response_body.extend(body_chunk)

                if more_body:
                    return

                # Если не JSON — пропускаем
                if "application/json" not in content_type:
                    await send(initial_message)
                    await send({"type": "http.response.body", "body": bytes(response_body)})
                    return

                try:
                    data = json.loads(response_body.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    await send(initial_message)
                    await send({"type": "http.response.body", "body": bytes(response_body)})
                    return

                # Добавляем guardian_meta только если есть "answer"
                if "answer" not in data:
                    await send(initial_message)
                    await send({"type": "http.response.body", "body": bytes(response_body)})
                    return

                user_id = request.query_params.get("user_id", "anonymous")
                try:
                    from app.routers.guardian_middleware import tracker
                    data["guardian_meta"] = tracker.process_api_call(user_id)
                except Exception as e:
                    data["guardian_meta"] = {"error": str(e)}

                new_body = json.dumps(data, ensure_ascii=False).encode("utf-8")

                # Пересчитываем Content-Length
                new_headers = [
                    (k, v)
                    for k, v in initial_message.get("headers", [])
                    if k.decode().lower() != "content-length"
                ]
                new_headers.append(
                    (b"content-length", str(len(new_body)).encode())
                )

                await send({**initial_message, "headers": new_headers})
                await send({"type": "http.response.body", "body": new_body})

        await self.app(scope, receive, send_wrapper)
