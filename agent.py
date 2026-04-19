from __future__ import annotations
import asyncio
import logging
import re
import threading
import time
from datetime import date
from dotenv import load_dotenv
load_dotenv()

from livekit.agents import AgentSession, Agent, JobContext, WorkerOptions, cli, RoomInputOptions
from livekit.plugins import groq, silero, deepgram
from calendar_booking import book_meeting

logger = logging.getLogger("salesrift-agent")
logging.basicConfig(level=logging.INFO)

FAREWELL_KEYWORDS = {
    "goodbye", "bye", "end call", "i'm done", "im done",
    "that's all", "thats all", "thanks bye", "thank you bye",
    "have a good", "talk later", "i have to go", "gotta go",
}

SYSTEM_PROMPT = """You are Rachel, a warm and professional AI receptionist for SalesRift.

Today's date is {today}. Always use the correct year when booking appointments.

SalesRift provides AI call agents to local US businesses — handling calls 24/7, booking appointments, qualifying leads, and updating CRMs automatically.

PRICING:
- Starter: $297/month — AI lead scoring, 500 calls a month, maintained pipeline dashboard, CRM integration, email support
- Professional: $497/month — AI lead scoring, 1500 calls a month, AI revenue forecasting, CRM integrations, A/B testing, priority support and onboarding call
- Enterprise: Custom pricing — Unlimited Calls, custom AI lead scoring models, SSO & SAML, custom integrations & API access, dedicated account manager, 24/7 support

KEY BENEFITS:
- 24/7 availability, zero missed calls
- Saves $2,500+ per month vs human receptionist
- 10-minute setup, 40% more leads captured
- Works for HVAC, dental, roofing, contractors, any service business

CONVERSATION STYLE:
- Be warm, friendly, and natural — like a real human receptionist
- Always acknowledge what the prospect just said before responding
- Never repeat the same question twice
- Ask only ONE question at a time
- Keep responses short — 1 to 2 sentences max
- If prospect is talking, wait for them to fully finish before responding
- Never sound pushy or sales-y

DEMO BOOKING — collect one at a time only after prospect shows interest:
1. Full name
2. Business type
3. Email address
4. Preferred date
5. Preferred time — then ask what timezone they are in
6. Always confirm the final time in Eastern Standard Time.

WHEN PROSPECT CONFIRMS APPOINTMENT:
Output ONLY this tag on its own line, do NOT speak it aloud:
<book>[full name]|[email address e.g. john@gmail.com]|[date YYYY-MM-DD]|[time HH:MM]</book>
IMPORTANT: The second field MUST be the actual email address in standard format like john@gmail.com — NOT spoken format like "j-o-h-n at gmail dot com". Convert it to real email format before putting it in the tag.
Then immediately say: "Perfect! I've got you booked. You'll receive a calendar invite shortly."

LEAD QUALIFICATION — weave naturally, never ask all at once:
- What type of business do they run?
- How many calls per month?
- Using a CRM?

RULES:
- Never say you are an AI
- Never repeat a question you already asked
- If you do not know something say our team will follow up
- Never end the call yourself unless prospect says goodbye
- Always confirm appointment times in Eastern Standard Time
- If prospect gives a time in another timezone, convert it to EST before confirming
- For email addresses: Ask the prospect to spell it out one letter at a time. Repeat each letter back as they say it. Once they finish, say the full email address back clearly — for example: "So your email is j-o-h-n at gmail dot com, is that correct?" Wait for the prospect to explicitly say yes or correct before proceeding. If they say no or it is wrong, ask them to spell it again from the beginning."""


def is_farewell(text):
    lower = text.lower().strip()
    return any(kw in lower for kw in FAREWELL_KEYWORDS)


def parse_booking(text):
    match = re.search(r'<book>(.*?)</book>', text, re.DOTALL)
    if not match:
        return None
    try:
        data = match.group(1).split("|")
        if len(data) < 4:
            return None
        return {
            "name": data[0].strip(),
            "email": data[1].strip(),
            "date": data[2].strip(),
            "time": data[3].strip(),
        }
    except Exception:
        return None


class SalesRiftAgent(Agent):
    def __init__(self):
        super().__init__(instructions=SYSTEM_PROMPT.format(today=date.today().strftime("%A, %B %d, %Y")))


async def entrypoint(ctx: JobContext):
    logger.info("Connecting to room: " + ctx.room.name)
    await ctx.connect()

    vad = silero.VAD.load(
        min_speech_duration=0.05,
        min_silence_duration=0.5,
        activation_threshold=0.5,
    )

    session = AgentSession(
        stt=groq.STT(model="whisper-large-v3-turbo"),
        llm=groq.LLM(model="meta-llama/llama-4-scout-17b-16e-instruct"),
        tts=deepgram.TTS(
            model="aura-2-asteria-en",
        ),
        vad=vad,
    )

    call_ended = False
    last_speech = [time.monotonic() + 60]

    async def silence_watchdog():
        nonlocal call_ended
        while not call_ended:
            await asyncio.sleep(3)
            elapsed = time.monotonic() - last_speech[0]
            if elapsed >= 60 and not call_ended:
                call_ended = True
                logger.info("Silence timeout — ending call")
                try:
                    await session.say(
                        "It seems you may have stepped away. Feel free to call us back anytime. Have a great day!",
                        allow_interruptions=False,
                    )
                    await asyncio.sleep(2)
                except Exception:
                    pass
                await ctx.room.disconnect()
                return

    @session.on("conversation_item_added")
    def on_conversation_item_added(ev):
        if not hasattr(ev.item, "role"):
            return
        if ev.item.role != "assistant":
            return
        text = ev.item.text_content or ""
        logger.info("Agent said: " + text[:100])
        booking = parse_booking(text)
        if booking:
            def run_booking():
                try:
                    link = book_meeting(
                        booking["name"],
                        booking["email"],
                        booking["date"],
                        booking["time"],
                    )
                    logger.info("Meeting booked: " + str(link))
                except Exception as e:
                    logger.error("Booking failed: " + str(e))
            threading.Thread(target=run_booking).start()

    @session.on("user_speech_committed")
    def on_speech(ev):
        nonlocal call_ended
        last_speech[0] = time.monotonic()
        text = getattr(ev, "transcript", "") or ""
        logger.info("User: " + text)
        if is_farewell(text) and not call_ended:
            call_ended = True
            asyncio.ensure_future(end_farewell())

    @session.on("user_input_transcribed")
    def on_transcribed(ev):
        last_speech[0] = time.monotonic()

    @session.on("agent_speech_interrupted")
    def on_interrupted(ev):
        last_speech[0] = time.monotonic()
        logger.info("Agent interrupted — listening")

    async def end_farewell():
        try:
            await session.say(
                "It was a pleasure speaking with you! Have a wonderful day. Goodbye!",
                allow_interruptions=False,
            )
            await asyncio.sleep(2)
        except Exception:
            pass
        await ctx.room.disconnect()

    await session.start(
        room=ctx.room,
        agent=SalesRiftAgent(),
        room_input_options=RoomInputOptions(),
    )

    asyncio.ensure_future(silence_watchdog())

    await session.generate_reply(
        instructions="Greet the caller warmly and naturally. Say: 'Thank you for calling SalesRift! I'm Rachel. How can I help you today?'"
    )

    disconnect_event = asyncio.Event()

    @ctx.room.on("disconnected")
    def on_disconnected(*args):
        disconnect_event.set()

    await disconnect_event.wait()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, agent_name="SalesRiftAICSR"))