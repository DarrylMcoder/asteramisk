# Introduction to Asteramisk

::: contents
Table of Contents
:::

[Asteramisk]{.title-ref} is a Python library for the Asterisk PBX. I
started working on this project about September or October 2024. It
started as an attempt to build a telephone interface for a ride sharing
system I was working on. While I was at it, I periodically gave up on
the ride sharing project and started a simpler telephone project.
projects that I have been working on use the same core code for
interaction with Asterisk PBX. I decided to clean it all up and put it
into a library for my own use and for anyone else who might find it
useful.

[Asteramisk]{.title-ref} is based on, or built on top of, the
\[panoramisk\](<https://github.com/gawel/panoramisk>) library. It
provides a server for handling incoming calls and text messages and a
[Communicator]{.title-ref} class for creating outgoing calls and
messaging conversations. Any communication, both phone calls and text
message conversations (and possibly other forms of communication in the
future), is represented by a [UI]{.title-ref} object. Each form of
communication has its own [UI]{.title-ref} subclass,
[VoiceUI]{.title-ref} for phone calls and [TextUI]{.title-ref} for text
messages. [UI]{.title-ref} objects provide methods loosely based on the
\[Twilio\](<https://www.twilio.com/docs>) API, such as
[answer]{.title-ref}, [play]{.title-ref}, [say]{.title-ref},
[gather]{.title-ref}, [record]{.title-ref}, and [hangup]{.title-ref}.

# Installation

[Asteramisk]{.title-ref} is available on
\[PyPI\](<https://pypi.org/project/asteramisk/>). You can install it
with [pip install asteramisk]{.title-ref}.

# Configuration

First, you need to configure Asterisk. You can find example
configuration files in [example_configs/]{.title-ref}. You should be
able to copy the [example_configs]{.title-ref} directory contents
directly into [/etc/asterisk/]{.title-ref}. You need to enable the
Asterisk ARI interface and the Asterisk AMI interface.

## AMI configuration

Make sure the AMI interface is enabled in Asterisk. Open the file
[/etc/asterisk/manager.conf]{.title-ref} and verify that the following
lines are present:

``` ini
[general]
enabled = yes
port = 5038
bindaddr = 0.0.0.0
```

In [/etc/asterisk/manager.d/]{.title-ref}, create a file named
[yourusername.conf]{.title-ref} and add the following lines:

``` ini
[yourusername]
secret = yourpassword
read = all
write = all
```

This will enable the AMI interface for the user
[yourusername]{.title-ref} with password [yourpassword]{.title-ref}. You
can then configure Asteramisk to use this user when connecting to
Asterisk AMI.

## ARI configuration

Make sure the ARI interface is enabled in Asterisk. This is a little
different from the AMI interface, but not any harder. Open the file
[/etc/asterisk/ari.conf]{.title-ref} and verify that the following lines
are present:

``` ini
[general]
enabled = yes
pretty = yes
```

In the same file, add the following lines:

``` ini
[yourariusername]
type=user
read_only=no
password=youraripassword
```

This will enable the ARI interface for the user
[yourariusername]{.title-ref} with password
[youraripassword]{.title-ref}.

Since the Rest API depends on Asterisk\'s built-in mini-http server, you
also need to make sure it is enabled in \`/etc/asterisk/http.conf\`:

``` ini
[general]
enabled=yes
bindaddr=0.0.0.0
```

::: warning
::: title
Warning
:::

By default, both the ARI interface and the mini-http server it depends
on are disabled. You need to enable them before Asteramisk will work.
:::

## Asteramisk configuration

Next, you need to configure Asteramisk to connect to your Asterisk PBX.
This is done by importing the [config]{.title-ref} module and setting
the following variables. Some of these variables are optional, but you
need to set the ones that are required to make Asteramisk work. See the
[config]{.title-ref} module for a complete list of configuration
variables.

``` python
from asteramisk.config import config

# Required configuration variables
config.ASTERISK_HOST = '127.0.0.1'

# Configure Asterisk AMI. Required for registering extensions, making calls and sending text messages
config.ASTERISK_AMI_PORT = 5038
config.ASTERISK_AMI_USER = 'yourusername' # Must be configured in Asterisk manager.conf
config.ASTERISK_AMI_PASS = 'yourpassword' # Must be configured in Asterisk manager.conf

# Configure Asterisk ARI interface. Required for handling incoming calls, playing audio, and general control of the call
config.ASTERISK_ARI_PORT = 8088 # The port on the Asterisk side where the Asterisk Rest API will be listening. Default is 8088
config.ASTERISK_ARI_USER = 'yourusername' # Must be configured in Asterisk ari.conf
config.ASTERISK_ARI_PASS = 'yourpassword' # Must be configured in Asterisk ari.conf

# Configure PSTN gateway. Required for making PSTN calls
config.ASTERISK_INCOMING_CALL_CONTEXT = 'from-pstn' # Context specified in context=yourcontext in Asterisk pjsip.conf under your endpoint configuration
config.ASTERISK_INCOMING_TEXT_CONTEXT = 'from-pstn' # Context specified in message_context=yourcontext in Asterisk pjsip.conf under your endpoint configuration
config.ASTERISK_PSTN_GATEWAY_HOST = 'toronto1.voip.ms' # The IP address or hostname of your SIP service provider. The POP server for PSTN calls
config.ASTERISK_PSTN_GATEWAY_PORT = 5060 # The port number of your SIP service provider
config.ASTERISK_PSTN_GATEWAY_USER = 'yourusername' # A username that has been configured with your SIP provider for authentication to your SIP account. Asteramisk needs it for outgoing PSTN calls

# Configure system information (optional)
config.SYSTEM_PHONE_NUMBER = '1234567890' # A phone number that has been configured with your SIP provider to be routed to your Asterisk endpoint
config.SYSTEM_NAME = 'Your Company Name' # A name that will be used in outgoing calls and text messages

# Optional configuration variables
config.ASTERISK_SOUNDS_DIR = '/usr/share/asterisk/sounds' # The directory where Asterisk stores its sound files. You need to set this only if you have changed the default location on the Asterisk side
config.ASTERISK_TTS_SOUNDS_SUBDIR = 'asteramisk' # The subdirectory where Asteramisk stores its TTS sound files. The default is fine, unless you don't like defaults, or unless you simply love writing unnecessary configuration.
config.AGI_SERVER_HOST = '127.0.0.1' # The ip address to bind the AGI server to. Default is 127.0.0.1
config.AGI_SERVER_PORT = 4753 # The port to bind the AGI server to. Default is 4753. You need to change this if you are running multiple instances of projects that use Asteramisk
```

# Usage

Once you have installed `Asteramisk`, and have the required
configuration variables set at the entry point of your code, you can
start coding your `Asteramisk` application. To create a server, import
the `Server` class from `asteramisk.server` and create a new instance of
it. You can then register extensions with the server using the
`register_extension` method. If your application should be accessible on
more than one phone number, simply repeat the `register_extension` call
for each number. Your call and text message handlers should be async
functions that accept a `UI` object as a parameter. Each call to a
handler will be handled by a separate coroutine.

``` python
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
```
