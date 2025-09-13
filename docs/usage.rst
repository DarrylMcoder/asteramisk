Usage
-----

Once you have installed ``Asteramisk``, and have the required configuration variables set at the entry point of your code, you can start coding your ``Asteramisk`` application.
To create a server, import the ``Server`` class from ``asteramisk.server`` and create a new instance of it.
You can then register extensions with the server using the ``register_extension`` method.
If your application should be accessible on more than one phone number, simply repeat the ``register_extension`` call for each number.
Your call and text message handlers should be async functions that accept a ``UI`` object as a parameter.
Each call to a handler will be handled by a separate coroutine.

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
            server = await Server.create(host='127.0.0.1', port=4753)
            await server.register_extension('1234567890', call_handler=my_call_handler, text_handler=my_text_handler)
            await server.serve_forever()

        if __name__ == '__main__':
            asyncio.run(main())

 Inside your call and text message handlers, you can use the ``UI`` object to control the call or text conversation.
 Use the :py:meth:`~asteramisk.ui.UI.answer` method to answer the call.
 Use the :py:meth:`~asteramisk.ui.UI.say` method to say something to the caller.
 Use the :py:meth:`~asteramisk.ui.UI.gather` method to gather digits from the caller.
 Use the :py:meth:`~asteramisk.ui.UI.prompt` method to prompt the caller for text input.
 Use the :py:meth:`~asteramisk.ui.UI.menu` method to present a menu to the caller and call a specified callback for the user's choice.
 Use the :py:meth:`~asteramisk.ui.UI.select` method to present a menu to the caller and get the user's choice.
 Use the :py:meth:`~asteramisk.ui.UI.hangup` method to hang up the call.

 The ``UI`` object also has a :py:meth:`~asteramisk.ui.UI.connect_openai_agent` method that allows you to connect your call or text conversation to an OpenAI agent.
 After calling this method, the conversation is controlled by the OpenAI agent.
 You can then use tool calling and other features of the OpenAI agent to control the conversation.
 Read more about OpenAI agents in the [OpenAI documentation](https://platform.openai.com/docs/guides/agents).

