"""WikiHow Massive Extractor — 200+ тем, Grok-4, связи, автосохранение."""
import json, urllib.request as req, time, re
from datetime import datetime

POLZA_KEY = "pza_Ns65_QseefnzOMML9WPpm8_Rhruu3fZ7"
MODEL = "x-ai/grok-4"
SKV_UPLOAD = "https://skv.network/api/v1/entries"
OUTPUT_FILE = "/root/skv-core/data/wikihow_massive_output.json"
LOG_FILE = "/root/skv-core/data/wikihow_massive.log"
AUTOSAVE_EVERY = 10

# 200+ реальных тем из WikiHow
TOPICS = [
    # Дом и ремонт (40 тем)
    "How to Fix a Leaking Faucet", "How to Unclog a Kitchen Sink", "How to Patch Drywall",
    "How to Paint a Room", "How to Fix a Running Toilet", "How to Remove Mold from Bathroom",
    "How to Replace a Light Switch", "How to Clean Stainless Steel Appliances",
    "How to Remove Carpet Stains", "How to Caulk a Bathtub", "How to Fix a Leaky Window",
    "How to Insulate an Attic", "How to Unclog a Toilet", "How to Reset a Circuit Breaker",
    "How to Clean Grout", "How to Replace a Shower Head", "How to Clean Gutters",
    "How to Fix a Garbage Disposal", "How to Replace a Faucet", "How to Fix Low Water Pressure",
    "How to Install a Ceiling Fan", "How to Fix a Squeaky Door", "How to Iron a Shirt",
    "How to Sew a Button", "How to Remove Grease Stains", "How to Clean a Microwave",
    "How to Descale a Kettle", "How to Organize a Pantry", "How to Declutter a Closet",
    "How to Fix a Leaky Roof", "How to Fix a Stuck Window", "How to Replace Weatherstripping",
    "How to Fix a Squeaky Floor", "How to Paint Kitchen Cabinets", "How to Install a Backsplash",
    "How to Fix a Broken Tile", "How to Remove Wallpaper", "How to Fix a Leaky Shower",
    "How to Replace a Toilet Seat", "How to Fix a Running Toilet Handle",
    
    # Автомобиль (20 тем)
    "How to Change a Car Tire", "How to Jump-Start a Car", "How to Check Engine Oil",
    "How to Replace Windshield Wipers", "How to Clean Car Headlights", "How to Check Tire Pressure",
    "How to Check Brake Pads", "How to Clean a Car Interior", "How to Remove Car Scratches",
    "How to Replace a Car Battery", "How to Change Spark Plugs", "How to Rotate Tires",
    "How to Replace Brake Lights", "How to Fix a Flat Tire", "How to Detail a Car Exterior",
    "How to Replace Cabin Air Filter", "How to Fix a Stuck Car Door", "How to Replace a Side Mirror",
    "How to Fix a Cracked Windshield", "How to Change Wiper Fluid",
    
    # Здоровье и фитнес (30 тем)
    "How to Start Running for Beginners", "How to Meditate for Beginners", "How to Improve Posture",
    "How to Fall Asleep Faster", "How to Perform CPR on an Adult", "How to Reduce Back Pain",
    "How to Start Intermittent Fasting", "How to Do Yoga at Home", "How to Start Weight Training",
    "How to Stretch Properly", "How to Count Calories", "How to Meal Plan for Weight Loss",
    "How to Quit Sugar", "How to Drink More Water", "How to Treat a Burn",
    "How to Treat a Cut", "How to Recognize Stroke Symptoms", "How to Help Someone Having a Seizure",
    "How to Use a Foam Roller", "How to Fix Flat Feet", "How to Improve Flexibility",
    "How to Build Core Strength", "How to Prevent Running Injuries", "How to Choose Running Shoes",
    "How to Treat Blisters", "How to Prevent Dehydration", "How to Recognize Heat Stroke",
    "How to Do a Proper Push-Up", "How to Treat a Sprained Ankle", "How to Stop a Nosebleed",
    
    # Финансы и карьера (25 тем)
    "How to Start Saving Money", "How to Build an Emergency Fund", "How to Create a Budget",
    "How to Invest Your First 100 Dollars", "How to Improve Credit Score", "How to Negotiate Salary",
    "How to Write a Resume", "How to Prepare for a Job Interview", "How to Give Constructive Feedback",
    "How to Ask for a Promotion", "How to Network Effectively", "How to Write a Cover Letter",
    "How to Follow Up After an Interview", "How to Negotiate Benefits", "How to File Taxes as Freelancer",
    "How to Avoid Investment Scams", "How to Start a Side Hustle", "How to Price Freelance Work",
    "How to Build a Portfolio", "How to Use LinkedIn for Jobs", "How to Deal with Difficult Coworkers",
    "How to Manage Stress at Work", "How to Work from Home Productively", "How to Avoid Burnout",
    "How to Prepare for a Performance Review",
    
    # Кулинария (20 тем)
    "How to Roast a Whole Chicken", "How to Make Perfect Scrambled Eggs", "How to Meal Prep for a Week",
    "How to Sharpen a Kitchen Knife", "How to Boil an Egg", "How to Make Coffee Without a Machine",
    "How to Store Fresh Herbs", "How to Freeze Vegetables", "How to Make Homemade Pizza",
    "How to Bake Bread", "How to Make Soup from Scratch", "How to Brew Beer at Home",
    "How to Make Jam", "How to Can Vegetables", "How to Cook Perfect Pasta",
    "How to Make a Smoothie", "How to Cook Rice Perfectly", "How to Fry an Egg",
    "How to Make Pancakes", "How to Bake Cookies",
    
    # Технологии и безопасность (20 тем)
    "How to Create a Strong Password", "How to Set Up Two-Factor Authentication",
    "How to Spot Phishing Emails", "How to Clean a Laptop Screen", "How to Speed Up a Windows PC",
    "How to Extend Phone Battery Life", "How to Secure Home WiFi", "How to Use a VPN",
    "How to Back Up Photos", "How to Edit a PDF", "How to Compress Images",
    "How to Factory Reset a Phone", "How to Transfer Data to a New Phone",
    "How to Clean a Mechanical Keyboard", "How to Set Up a Home Office Network",
    "How to Block Spam Calls", "How to Use Google Calendar Effectively",
    "How to Organize Email Inbox", "How to Do a Digital Detox", "How to Learn Touch Typing",
    
    # Путешествия (15 тем)
    "How to Pack for a Trip", "How to Travel on a Budget", "How to Find Cheap Flights",
    "How to Avoid Jet Lag", "How to Pack a Carry-On Only", "How to Stay Safe While Traveling Alone",
    "How to Exchange Currency", "How to Use Public Transport Abroad", "How to Order Food in a Foreign Language",
    "How to Ask for Directions", "How to Haggle at a Market", "How to Tip in Different Countries",
    "How to Rent an Apartment Abroad", "How to Buy a Used Car", "How to Read a Contract",
    
    # Саморазвитие (20 тем)
    "How to Overcome Procrastination", "How to Build a Morning Routine", "How to Focus Deeply",
    "How to Learn a Foreign Language", "How to Read a Book Per Week", "How to Start Journaling",
    "How to Practice Gratitude", "How to Set SMART Goals", "How to Use a Planner Effectively",
    "How to Overcome Fear of Public Speaking", "How to Make Small Talk", "How to Apologize Sincerely",
    "How to Set Boundaries", "How to Make Friends as an Adult", "How to Plan a Date",
    "How to Write a Wedding Speech", "How to Support a Grieving Friend", "How to Donate to Charity Effectively",
    "How to Start Volunteering", "How to Reduce Plastic Use",
    
    # Экология и дом (10 тем)
    "How to Save Electricity at Home", "How to Recycle Properly", "How to Start Composting",
    "How to Grow Vegetables at Home", "How to Care for Succulents", "How to Repot a Plant",
    "How to Grow Herbs Indoors", "How to Fix a Bicycle Chain", "How to Change a Bike Tire",
    "How to Build a Campfire Safely",
]

PROMPT = """Create high-quality experience cube(s) with 9-12 rules each (MUST/PROHIBITED/WARNING), 6-8 trigger_intent phrases, 2-3 sentence rationale. Be specific with tools and steps. If the topic is complex, create multiple cubes covering different aspects. Source: wikihow. Return ONLY valid JSON array. Topic: {TOPIC}"""

def make_cube_id(title):
    slug = re.sub(r'[^a-z0-9]+', '_', title.lower()).strip('_')[:60]
    return f"cube_exp_{slug}"

def log(msg):
    timestamp = datetime.now().strftime('%H:%M:%S')
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')

def generate_cubes(topic):
    prompt = PROMPT.replace("{TOPIC}", topic)
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.25,
        "max_tokens": 1500
    }).encode()
    
    r = req.Request("https://api.polza.ai/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {POLZA_KEY}"})
    
    with req.urlopen(r, timeout=180) as resp:
        result = json.loads(resp.read())
        content = result["choices"][0]["message"]["content"].strip()
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        cubes = json.loads(content)
        if isinstance(cubes, dict):
            cubes = [cubes]
        for c in cubes:
            c['cube_id'] = make_cube_id(c.get('title', 'untitled'))
        return cubes

def upload_batch(cubes):
    body = json.dumps({"cubes": cubes}).encode()
    r = req.Request(SKV_UPLOAD, data=body, headers={"Content-Type": "application/json"})
    resp = json.loads(req.urlopen(r, timeout=60).read())
    return resp.get('cubes_loaded', 0)

# ====================== MAIN ======================
log(f"🌙 WikiHow Massive Extractor — {len(TOPICS)} topics, Grok-4")
log(f"💾 Autosave every {AUTOSAVE_EVERY} topics")

cubes_all = []
success = 0
for i, topic in enumerate(TOPICS, 1):
    log(f"[{i}/{len(TOPICS)}] {topic[:60]}...")
    try:
        cubes = generate_cubes(topic)
        cubes_all.extend(cubes)
        success += 1
        log(f"  OK {len(cubes)} cubes (total: {len(cubes_all)})")
        time.sleep(0.5)
        
        if i % AUTOSAVE_EVERY == 0:
            with open(OUTPUT_FILE, "w") as f:
                json.dump({"cubes": cubes_all, "count": len(cubes_all)}, f, indent=2)
            
            if len(cubes_all) >= 50:
                try:
                    loaded = upload_batch(cubes_all[:50])
                    log(f"  Uploaded: {loaded} cubes")
                    cubes_all = cubes_all[50:]
                except Exception as e:
                    log(f"  Upload error: {e}")
    except Exception as e:
        log(f"  Error: {str(e)[:80]}")

if cubes_all:
    with open(OUTPUT_FILE, "w") as f:
        json.dump({"cubes": cubes_all, "count": len(cubes_all)}, f, indent=2)
    try:
        loaded = upload_batch(cubes_all)
        log(f"  Final upload: {loaded} cubes")
    except Exception as e:
        log(f"  Final error: {e}")

info = json.loads(req.urlopen("https://skv.network/api/v1/info", timeout=10).read())
log(f"Total cubes in SKV: {info.get('cubes_count', '?')}")
log(f"Done! ({success}/{len(TOPICS)} successful)")
