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
Use the ``gather`` method to gather digits from the caller.
Use the ``prompt`` method to prompt the caller for text input.
Use the ``menu`` method to present a menu to the caller and call a specified callback for the user's choice.
Use the ``select`` method to present a menu to the caller and get the user's choice.
Use the ``hangup`` method to end the call or text session.

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
Read more about OpenAI agents in the [OpenAI documentation](https://platform.openai.com/docs/guides/agents).
