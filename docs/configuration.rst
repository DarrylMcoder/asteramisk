Configuration
-------------
First, you need to configure Asterisk.
You can find example configuration files in `example_configs/`.
You should be able to copy the `example_configs` directory contents directly into `/etc/asterisk/`.
You need to enable the Asterisk ARI interface and the Asterisk AMI interface.

AMI configuration
*****************
Make sure the AMI interface is enabled in Asterisk.
Open the file `/etc/asterisk/manager.conf` and verify that the following lines are present:

.. code-block:: ini

        [general]
        enabled = yes
        port = 5038
        bindaddr = 0.0.0.0

In `/etc/asterisk/manager.d/`, create a file named `yourusername.conf` and add the following lines:

.. code-block:: ini

        [yourusername]
        secret = yourpassword
        read = all
        write = all

This will enable the AMI interface for the user `yourusername` with password `yourpassword`.
You can then configure Asteramisk to use this user when connecting to Asterisk AMI.

ARI configuration
*****************
Make sure the ARI interface is enabled in Asterisk.
This is a little different from the AMI interface, but not any harder.
Open the file `/etc/asterisk/ari.conf` and verify that the following lines are present:

.. code-block:: ini

        [general]
        enabled = yes
        pretty = yes

In the same file, add the following lines:

.. code-block:: ini

        [yourariusername]
        type=user
        read_only=no
        password=youraripassword

This will enable the ARI interface for the user `yourariusername` with password `youraripassword`.

Since the Rest API depends on Asterisk's built-in mini-http server, you also need to make sure it is enabled in `/etc/asterisk/http.conf`:

.. code-block:: ini

        [general]
        enabled=yes
        bindaddr=0.0.0.0

.. warning::
   By default, both the ARI interface and the mini-http server it depends on are disabled.
   You need to enable them before Asteramisk will work.


Asteramisk configuration
************************
Next, you need to configure Asteramisk to connect to your Asterisk PBX.
This is done by importing the `config` module and setting the following variables.
Some of these variables are optional, but you need to set the ones that are required to make Asteramisk work.
See the `config` module for a complete list of configuration variables.

.. code-block:: python

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

