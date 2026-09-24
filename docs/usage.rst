Usage
-----

Once you have installed ``Asteramisk``, and have the required configuration variables set at the entry point of your code, you can start coding your ``Asteramisk`` application.
To create a server, import the ``Server`` class from ``asteramisk.server`` and create a new instance of it.
You can then register extensions with the server using the ``register_extension`` method.
If your application should be accessible on more than one phone number, simply repeat the ``register_extension`` call for each number.
Your call and text message handlers should be async functions that accept a ``UI`` object as a parameter.
Each call or text message is handled by a separate asyncio task so that multiple conversations can be handled concurrently.

.. code-block:: python

        import asyncio
        from asteramisk.server import Server
        from asteramisk.ui import VoiceUI, TextUI

        async def my_call_handler(ui: VoiceUI):
            await ui.answer()
            await ui.say('Hello, world!')
            digit = await ui.gather("Please pick a number between 1 and 10", num_digits=1)
            await ui.say(f"You pressed {digit}")
            await ui.menu('For option 1, press 1. For option 2, press 2.', callbacks={
                '1': async_callback_1,
                '2': async_callback_2
            })
            await ui.hangup()

        async def my_text_handler(ui: TextUI):
            await ui.answer()
            await ui.say('Hello, world!')
            name = await ui.prompt('What is your name?')
            await ui.say(f"Hello, {name}")
            await ui.say(f"Goodbye, {name}")
            await ui.hangup()

        async def main():
            server = await Server.create()
            await server.register_extension('1234567890', call_handler=my_call_handler, message_handler=my_text_handler)
            await server.serve_forever()

        if __name__ == '__main__':
            asyncio.run(main())

``Server``, ``Communicator``, and ``VoiceUI`` share one process-local ARI
application and event connection. A standalone ``Communicator`` starts that
connection automatically. If you pass a custom ``stasis_app`` to
``Server.create()``, create the server before creating a ``Communicator``; an
active shared ARI application cannot be renamed.

Inside your call and text message handlers, you can use the ``UI`` object to control the call or text conversation.
Use the ``answer`` method to perform any setup needed before communication.
Use the ``say`` method to speak or send a message to the other party.

On voice calls, use ``sleep`` to queue a pause between spoken messages::

    await ui.say('Please wait')
    await ui.sleep(2)
    await ui.say('Thank you')

For ``VoiceUI``, ``sleep`` queues up to one hour of silence and returns
immediately. Longer pauses raise ``ValueError``. For ``TextUI``, it waits for
the requested duration before returning, delaying the next operation.
Use the ``gather`` method to gather digits from the caller.
Use the ``prompt`` method to prompt the caller for text input.
Use the ``menu`` method to present a menu to the caller and call a specified callback for the user's choice.
Use the ``select`` method to present a menu to the caller and get the user's choice.
Use the ``hangup`` method to end the call or text session.

``ask_yes_no`` uses ``1`` for true and ``2`` for false on voice calls.
Customize each medium's instruction while sharing the main text::

    correct = await ui.ask_yes_no(
        "Your name is Bob.",
        voice_instruction="If that's correct, press 1. Otherwise, press 2.",
        text_instruction="Is that correct? (yes/no)",
    )

Each instruction replaces its medium's default suffix. When omitted or set
to ``None``, ``voice_instruction`` defaults to ``Press 1 for yes or 2 for no``
and ``text_instruction`` defaults to ``(yes/no)``. An empty string suppresses
the suffix. Each UI ignores the other medium's instruction. Text answers
remain ``yes``/``y`` and ``no``/``n``. Retries repeat the full question and
the selected instruction.

Text sessions have an explicit lifecycle. Once ``TextUI.hangup()`` is called,
that UI is closed and cannot send or receive further messages. A later incoming
message starts a new handler with a new ``TextUI``. For outgoing conversations,
call ``Communicator.make_text()`` again to create a new session.

OpenAI agents
*************

The shared ``UI.run_agent()`` method connects either a ``VoiceUI`` or ``TextUI``
to a non-realtime OpenAI ``Agent``:

.. code-block:: python

        from agents import Agent

        agent = Agent(name="Assistant", instructions="Be helpful and concise.")
        async with ui.run_agent(agent) as session:
            async for event in session:
                pass

Both UIs also provide ``run_realtime_agent()`` for an
``agents.realtime.RealtimeAgent``. VoiceUI sends audio; TextUI sends messages
using text-only modalities:

.. code-block:: python

        from agents.realtime import RealtimeAgent

        agent = RealtimeAgent(name="Assistant", instructions="Be helpful.")
        async with ui.run_realtime_agent(agent) as session:
            async for event in session:
                pass

Do not use ``await`` before either context-manager method.
Leaving ``run_realtime_agent()`` closes its event stream and SDK session and
stops its input task, including after an early ``break`` or an exception.
VoiceUI waits for queued speech before starting and supports star navigation
during the agent conversation. TextUI accepts ``back`` or ``*`` to go back;
these messages are not forwarded to the agent. TextUI does not wait for output.
Back navigation raises ``GoBackException`` through the context so an enclosing
menu can handle it normally. Consume the yielded stream inside its context.
Read more about OpenAI agents in the [OpenAI documentation](https://platform.openai.com/docs/guides/agents).

Menu back navigation
--------------------

When star navigation is enabled, pressing ``*`` in a submenu returns to its
parent menu. A back event that reaches the root menu keeps the caller at the
root. Menu replay uses a loop, so another pending back event during replay does
not escape the menu or add a recursive call.

Controlled playback
-------------------

``await ui.control_say(text, skip_seconds=15)`` reads text with key 4 to rewind,
key 5 to pause or resume, and key 6 to skip forward. ``skip_seconds`` is
keyword-only and defaults to three seconds. VoiceUI converts the interval to
whole milliseconds for Asterisk. Use a positive, finite interval of at least
one millisecond. TextUI accepts the same argument but simply sends the text.

Optional activity events
------------------------

Register a synchronous, lightweight listener on an individual UI::

    def receive_event(event):
        queue.put_nowait(event)  # Your application owns this bounded queue.

    unsubscribe = ui.add_event_listener(receive_event)
    try:
        await run_service(ui)
    finally:
        unsubscribe()
        # Your application may now drain its queue with a bounded timeout.

An ``asteramisk.events.UIEvent`` has ``id``, timezone-aware UTC ``occurred_at``,
``kind``, and a ``data`` dictionary. Treat events as read-only. Listeners run
on the call's asyncio loop; they must not block, write to a database, or return
an awaitable. Exceptions are caught without logging payloads. With no listener,
operations proceed normally. Registration returns an idempotent unsubscribe
function. The library stores no events and performs no price calculations.

Available events and fields:

* ``speech.tts``: cache hit, voice, character count; provider and outcome for
  generated audio. Google usage is reported per actual request chunk, including
  successful chunks preceding a failure. No text or audio is included.
* ``speech.recognition``: provider/model, submitted audio seconds, outcome.
  This is measured PCM usage, not provider billing rounding; no transcript.
* ``speech_input.started/ended`` and ``speech_input.result``: operation ID,
  elapsed seconds, outcome, empty input. Text prompts use ``text_input``.
* ``menu.action.started/ended``: callback name, operation ID, elapsed time,
  outcome. Keypad values and callback arguments are never included.
* ``content.playback.started/ended``: controlled-playback operation lifecycle.
* ``realtime.started/ended``: agent, model, operation ID, outcome, elapsed time.
  This operation ID is the ``segment_id`` on the following events.
* ``realtime.usage``: response ID, model, raw token usage, status, segment ID.
* ``realtime.response_started``: response ID and segment ID, allowing consumers
  to identify responses that end without returned usage.
* ``conversation.input``: transcript/text, item ID when available, segment ID,
  and separate input-transcription usage when supplied by the provider.
* ``conversation.output``: generated answer, response/item/segment IDs, status.
* ``realtime.audio_end/audio_interrupted/error``: selected SDK notifications.

Conversation content is exposed only during explicit agent conversations.
Do not register a persistent recorder where collecting that content is unwanted.
Generated output and SDK audio-end events are not proof the caller heard the
whole answer. Input transcription has separate usage from realtime responses.
See the `OpenAI realtime documentation <https://developers.openai.com/api/docs/guides/realtime-conversations>`_.

UI methods pass a request-scoped ``event_callback`` to speech engines. The
shared TTS engine never retains a caller's callback. Direct engine callers may
provide this optional keyword themselves. Preserve it when implementing a custom
engine if events are required. Listener failure does not change call navigation.
