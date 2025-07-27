Configuration
-------------
First, you need to configure Asteramisk to connect to your Asterisk PBX.
This is done by importing the `config` module and setting the following variables.
Some of these variables are optional, but you need to set the ones that are required to make Asteramisk work.
See the `config` module for more details.

.. code-block:: python

        from asteramisk.config import config

        # Required configuration variables
        config.ASTERISK_HOST = '127.0.0.1'
        config.ASTERISK_AMI_PORT = 5038
        config.ASTERISK_AMI_USER = 'yourusername' # Must be configured in Asterisk manager.conf
        config.ASTERISK_AMI_PASS = 'yourpassword' # Must be configured in Asterisk manager.conf
        config.ASTERISK_PSTN_CONTEXT
        config.ASTERISK_INCOMING_CALL_CONTEXT = 'from-pstn' # Context specified in context=yourcontext in Asterisk pjsip.conf under your endpoint configuration
        config.ASTERISK_INCOMING_TEXT_CONTEXT = 'from-pstn' # Context specified in message_context=yourcontext in Asterisk pjsip.conf under your endpoint configuration
        config.ASTERISK_PSTN_GATEWAY_HOST = 'toronto1.voip.ms' # The IP address or hostname of your SIP service provider. The POP server for PSTN calls
        config.ASTERISK_PSTN_GATEWAY_PORT = 5060 # The port number of your SIP service provider
        config.ASTERISK_PSTN_GATEWAY_USER = 'yourusername' # A username that has been configured with your SIP provider for authentication to your SIP account. Asteramisk needs it for outgoing PSTN calls
        config.SYSTEM_PHONE_NUMBER = '1234567890' # A phone number that has been configured with your SIP provider to be routed to your Asterisk endpoint
        config.SYSTEM_NAME = 'Your Company Name' # A name that will be used in outgoing calls and text messages

        # Optional configuration variables
        config.ASTERISK_SOUNDS_DIR = '/usr/share/asterisk/sounds' # The directory where Asterisk stores its sound files. You need to set this only if you have changed the default location on the Asterisk side
        config.ASTERISK_TTS_SOUNDS_SUBDIR = 'asteramisk' # The subdirectory where Asteramisk stores its TTS sound files. The default is fine, unless you don't like defaults, or unless you simply love writing unnecessary configuration.
        config.AGI_SERVER_HOST = '127.0.0.1' # The ip address to bind the AGI server to. Default is 127.0.0.1
        config.AGI_SERVER_PORT = 4753 # The port to bind the AGI server to. Default is 4753. You need to change this if you are running multiple instances of projects that use Asteramisk


