import json, sys, time, urllib.request
BASE = sys.argv[1]; MODEL = sys.argv[2]; OUT = sys.argv[3]
QUESTIONS = [
 "What kinds of questions and services can you help me with?",
 "What is the refund policy if I cancel my ticket, and are there refund fees?",
 "What happens if my flight is delayed for several hours? Do you provide meals, hotels or compensation?",
 "What should I do if my flight is cancelled? Can I be rebooked or get a refund?",
 "What is the free checked baggage allowance for an economy class ticket?",
 "My checked baggage did not arrive. How do I report lost or delayed baggage and what compensation is available?",
 "How much does it cost to change the date of my flight?",
 "I use a wheelchair. How can I request special assistance at the airport and on board?",
 "Can I fly while pregnant? Are there any restrictions or documents needed?",
 "Can a child travel alone? What is the unaccompanied minor service?",
 "How can I file a complaint about the service I received?",
 "How can I upgrade my seat to a higher class using miles or payment?",
 "Can I bring my pet on the flight?",
 "I have a medical condition and need oxygen during the flight. What should I do?",
]
results = []
for q in QUESTIONS:
    body = json.dumps({"model": MODEL, "messages": [{"role": "user", "content": q}]}).encode()
    req = urllib.request.Request(BASE + "/chat/completions", body, {"Content-Type": "application/json"})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            a = json.load(r)["choices"][0]["message"]["content"]
    except Exception as e:
        a = f"ERROR: {e}"
    results.append({"question": q, "answer": a, "seconds": round(time.time() - t, 1)})
    print(f"[{results[-1]['seconds']}s] {q}\n  -> {a[:300]!r}\n", flush=True)
json.dump(results, open(OUT, "w"), ensure_ascii=False, indent=2)
