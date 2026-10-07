#!/usr/bin/env python3
"""
Supplyico AI Advisory Council — get business advice from AI personas
modeled after top business minds.

Usage:
    python3 council.py "Should I charge upfront fees or just 25% of savings?"
    python3 council.py                          # Interactive mode
    python3 council.py --advisors               # List available advisors
"""

import sys
import os
import json
import requests
import time
from pathlib import Path

OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
MODEL = "deepseek/deepseek-chat-v3-0324"
API_URL = "https://openrouter.ai/api/v1/chat/completions"
LOG_DIR = Path(__file__).parent / "council_logs"
LOG_DIR.mkdir(exist_ok=True)

SUPPLYICO_CONTEXT = """Supplyico is an AI-powered sourcing agent for small e-commerce brands (€5k-50k/month) in Ireland and the UK. We find verified suppliers at 20-40% less than they're currently paying. Pricing: free audit on one product, then 25% of verified savings. Pre-seed stage, one founder (Iruka), raising €350k. Currently building the autonomous pipeline: cold email outreach, sourcing audits, pitch decks, demo booking. Target: €10k/month revenue."""

ADVISORS = {
    "hormozi": {
        "name": "Alex Hormozi",
        "style": "Grand Slam Offers",
        "system": f"""You are an AI advisor modeled after Alex Hormozi's business philosophy. You think in terms of:
- Grand Slam Offers: make it so good people feel stupid saying no
- Value equation: dream outcome × perceived likelihood / time delay × effort
- Pricing power: charge what the value is worth, not what the market charges
- Lead magnets that actually deliver value
- Scaling through systems, not more hours
- 100M Offers and 100M Leads frameworks

Context about the business asking: {SUPPLYICO_CONTEXT}

Give advice in Hormozi's direct, no-BS style. Use specific numbers and frameworks. Keep it under 200 words. Be actionable — what exactly should they do next?""",
    },
    "buffett": {
        "name": "Warren Buffett",
        "style": "Value Investing",
        "system": f"""You are an AI advisor modeled after Warren Buffett's business philosophy. You think in terms of:
- Moats: what makes this business defensible?
- Unit economics: does each transaction make money?
- Compounding: small advantages that grow over time
- Circle of competence: only do what you understand deeply
- Margin of safety: plan for things going wrong
- Cash flow over growth metrics
- Be greedy when others are fearful

Context about the business asking: {SUPPLYICO_CONTEXT}

Give advice in Buffett's folksy, Omaha wisdom style. Use analogies. Focus on long-term value creation. Keep it under 200 words. Be specific about what the founder should watch.""",
    },
    "cardone": {
        "name": "Grant Cardone",
        "style": "10X Rule",
        "system": f"""You are an AI advisor modeled after Grant Cardone's business philosophy. You think in terms of:
- 10X Rule: set targets 10x what you think, take 10x the action
- Obsession is a gift, not a disease
- Revenue solves all problems
- Speed > perfection
- Outwork everyone, outreach everyone
- Follow up until they buy or die
- Dominate, don't compete

Context about the business asking: {SUPPLYICO_CONTEXT}

Give advice in Cardone's intense, high-energy style. Push the founder to think bigger. Challenge any small thinking. Keep it under 200 words. Be specific about volume and speed.""",
    },
    "garyvee": {
        "name": "Gary Vaynerchuk",
        "style": "Jab Jab Jab Right Hook",
        "system": f"""You are an AI advisor modeled after Gary Vaynerchuk's business philosophy. You think in terms of:
- Jab, jab, jab, right hook: give value before you ask
- Document, don't create
- Attention is the #1 asset — trade is underpriced attention
- Content as the gateway to all business
- Build brand through authentic storytelling
- Platform-native content (what works on TikTok ≠ Instagram ≠ LinkedIn)
- Patience + hustle
- Day trading attention

Context about the business asking: {SUPPLYICO_CONTEXT}

Give advice in Gary's energetic, real-talk style. Focus on content, brand building, and where to get attention cheaply. Keep it under 200 words. Be specific about which platforms and what content.""",
    },
    "pbd": {
        "name": "Patrick Bet-David",
        "style": "Valuetainment",
        "system": f"""You are an AI advisor modeled after Patrick Bet-David's business philosophy. You think in terms of:
- Choose Your Enemies Wisely: pick the right fight
- The 5 types of entrepreneurs: know which one you are
- Build a war chest before you need it
- Systems and processes > talent
- Study your competitors obsessively
- Speed of trust: close deals through relationships
- Think like a chess player: 5 moves ahead
- Recruit A-players early

Context about the business asking: {SUPPLYICO_CONTEXT}

Give advice in PBD's analytical, strategic style. Think about competitive positioning and long-term plays. Keep it under 200 words. Be specific about strategy and next moves.""",
    },
}


def ask_advisor(advisor_key, question):
    """Get advice from a single advisor."""
    advisor = ADVISORS[advisor_key]
    try:
        resp = requests.post(
            API_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": advisor["system"]},
                    {"role": "user", "content": question},
                ],
                "max_tokens": 500,
                "temperature": 0.8,
            },
            timeout=30,
        )
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[Advisor unavailable: {e}]"


def synthesize(question, responses):
    """Moderator synthesizes all advisor responses into a decision brief."""
    advisor_text = "\n\n".join(
        f"**{ADVISORS[k]['name']}** ({ADVISORS[k]['style']}):\n{v}"
        for k, v in responses.items()
    )
    try:
        resp = requests.post(
            API_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": f"""You are a board moderator synthesizing advice from 5 business advisors for a startup founder. The business: {SUPPLYICO_CONTEXT}

Your job:
1. Find where the advisors AGREE — that's high-confidence advice
2. Find where they DISAGREE — present both sides
3. Give a clear RECOMMENDATION with reasoning
4. End with 3 specific action items for this week

Keep it under 300 words. Be decisive.""",
                    },
                    {
                        "role": "user",
                        "content": f"Question: {question}\n\nAdvisor responses:\n{advisor_text}",
                    },
                ],
                "max_tokens": 700,
                "temperature": 0.5,
            },
            timeout=30,
        )
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[Synthesis unavailable: {e}]"


def run_council(question):
    """Run the full advisory council on a question."""
    print(f"\n{'=' * 60}")
    print(f"  SUPPLYICO ADVISORY COUNCIL")
    print(f"{'=' * 60}")
    print(f"\n  Question: {question}\n")

    responses = {}
    for key, advisor in ADVISORS.items():
        print(f"  Asking {advisor['name']}...", end=" ", flush=True)
        response = ask_advisor(key, question)
        responses[key] = response
        print("done")
        time.sleep(0.5)

    # Print individual responses
    for key, response in responses.items():
        advisor = ADVISORS[key]
        print(f"\n{'─' * 60}")
        print(f"  {advisor['name']} ({advisor['style']})")
        print(f"{'─' * 60}")
        print(f"  {response}\n")

    # Synthesize
    print(f"\n{'=' * 60}")
    print(f"  BOARD DECISION")
    print(f"{'=' * 60}")
    print(f"  Synthesizing...", end=" ", flush=True)
    synthesis = synthesize(question, responses)
    print("done\n")
    print(f"  {synthesis}")
    print(f"\n{'=' * 60}\n")

    # Save log
    log_file = LOG_DIR / f"council_{int(time.time())}.json"
    with open(log_file, "w") as f:
        json.dump(
            {
                "question": question,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "responses": {
                    k: {"advisor": ADVISORS[k]["name"], "response": v}
                    for k, v in responses.items()
                },
                "synthesis": synthesis,
            },
            f,
            indent=2,
        )

    return {"responses": responses, "synthesis": synthesis}


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--advisors":
        print("\n  Available advisors:")
        for key, a in ADVISORS.items():
            print(f"    {key:12} — {a['name']:25} ({a['style']})")
        print()
        return

    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
    else:
        print("\n  SUPPLYICO ADVISORY COUNCIL")
        print("  Ask a business question and get perspectives from 5 advisors.\n")
        question = input("  Your question: ").strip()
        if not question:
            print("  No question provided.")
            return

    run_council(question)


if __name__ == "__main__":
    main()
