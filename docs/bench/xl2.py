import json, sys
sys.path.insert(0, "/app")
import numpy as np
from app import semantic as S
S.MODELS["mpnet"] = {"name": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2", "dim": 768, "dir": "/data/skv/hnsw_mpnet", "table": "pvec_mpnet"}
P = [  # (english memory, russian memory, russian query, english query)
("My sister Anna moved to Lisbon last spring.", "Моя сестра Анна переехала в Лиссабон прошлой весной.", "Куда переехала сестра?", "Where did my sister move?"),
("Our cat is called Pushok and he hates the vacuum cleaner.", "Нашего кота зовут Пушок, он ненавидит пылесос.", "Как зовут кота?", "What is the cat's name?"),
("The backup server runs every night at 3 am.", "Сервер бэкапов запускается каждую ночь в 3 часа.", "Во сколько делается резервная копия?", "When does the backup run?"),
("I am allergic to peanuts.", "У меня аллергия на арахис.", "На что у меня аллергия?", "What am I allergic to?"),
("We decided to keep SQLite, one database per user.", "Мы решили оставить SQLite, по одной базе на пользователя.", "Какую базу данных мы выбрали?", "Which database did we choose?"),
("My dentist appointment is on Friday at 10.", "Запись к стоматологу в пятницу в 10.", "Когда мне к зубному врачу?", "When is my dentist appointment?"),
("Dmitry prefers tea without sugar.", "Дмитрий любит чай без сахара.", "Какой чай пьёт Дмитрий?", "How does Dmitry take his tea?"),
("The car needs new winter tires before November.", "Машине нужна новая зимняя резина до ноября.", "Что нужно сделать с автомобилем?", "What does the car need?"),
("I started learning to play the guitar in August.", "В августе я начал учиться играть на гитаре.", "Каким музыкальным инструментом я занимаюсь?", "Which instrument am I learning?"),
("The project budget for testing is 80 rubles.", "Бюджет проекта на тесты — 80 рублей.", "Сколько денег выделено на тестирование?", "How much money is allocated for testing?"),
("My daughter goes to swimming lessons on Tuesdays.", "Дочь ходит на плавание по вторникам.", "В какой день у дочки бассейн?", "Which day is my daughter's swimming class?"),
("We are flying to Istanbul on the 12th of December.", "Мы летим в Стамбул 12 декабря.", "Куда и когда мы летим?", "Where are we flying in December?"),
("The landlord raised the rent by ten percent.", "Хозяин квартиры поднял аренду на десять процентов.", "Насколько подорожала квартира?", "How much did the rent go up?"),
("I quit smoking three months ago.", "Я бросил курить три месяца назад.", "Когда я бросил курить?", "When did I stop smoking?"),
("Grandma's birthday is on March 8.", "День рождения бабушки 8 марта.", "Когда день рождения у бабушки?", "When is grandma's birthday?"),
("The office Wi-Fi drops every afternoon around 4 pm.", "Офисный вайфай отваливается каждый день около 16:00.", "Когда пропадает интернет в офисе?", "When does the office internet fail?"),
("My favourite book is The Master and Margarita.", "Моя любимая книга — «Мастер и Маргарита».", "Какая у меня любимая книга?", "What is my favorite novel?"),
("Igor owes me five thousand rubles.", "Игорь должен мне пять тысяч рублей.", "Кто мне должен деньги?", "Who owes me money?"),
("The guard must never return an empty answer.", "Guard никогда не должен отдавать пустой ответ.", "Может ли гард оставить без ответа?", "Can the guard leave the user with no reply?"),
("I run 5 kilometres every Sunday morning.", "Каждое воскресенье утром я бегаю 5 километров.", "Как часто я бегаю?", "How often do I go running?"),
("The new laptop has 32 GB of RAM.", "В новом ноутбуке 32 ГБ оперативной памяти.", "Сколько памяти в ноутбуке?", "How much memory does the laptop have?"),
("My son broke his arm playing football.", "Сын сломал руку, играя в футбол.", "Что случилось с сыном?", "What happened to my son?"),
("We planted tomatoes and cucumbers at the dacha.", "На даче мы посадили помидоры и огурцы.", "Что растёт на даче?", "What did we plant at the country house?"),
("The meeting with investors was moved to Thursday.", "Встречу с инвесторами перенесли на четверг.", "Когда встреча с инвесторами?", "When is the investor meeting?"),
("I prefer working at night when it is quiet.", "Мне нравится работать ночью, когда тихо.", "В какое время суток я люблю работать?", "When do I like to work?"),
]
D=[]
_d=json.load(open("/tmp/ab768/locomo10.json"))
for c in _d[5:8]:
    c=c["conversation"]
    for k in c:
        if k.startswith("session_") and not k.endswith("date_time"):
            D+= [t["text"] for t in c[k] if len(t["text"])>40]
D=D[:600]
def run(tag):
    out = {}
    DV = S.embed(D, tag)
    for name, mi, qi in (("ru_query->en_memory", 0, 2), ("en_query->ru_memory", 1, 3), ("ru->mixed", None, 2), ("en->mixed", None, 3)):
        if mi is None: mem = [p[i % 2] for i, p in enumerate(P)]
        else: mem = [p[mi] for p in P]
        M = np.vstack([S.embed(mem, tag), DV]); Q = S.embed([p[qi] for p in P], tag)
        s = Q @ M.T; r = np.argsort(-s, axis=1)
        out[name] = {"hit@1": round(float(np.mean(r[:, 0] == np.arange(len(P)))), 2),
                     "hit@3": round(float(np.mean([i in r[i, :3] for i in range(len(P))])), 2)}
    return out
import resource
for t in sys.argv[1].split(","): print(t, json.dumps(run(t), ensure_ascii=False), "rss", resource.getrusage(resource.RUSAGE_SELF).ru_maxrss//1024, flush=True)
