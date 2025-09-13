Introduction to Asteramisk
---------------------------

.. contents:: Table of Contents

``Asteramisk`` is a Python library for the Asterisk PBX.
I started working on this project about September or October 2024.
It started as an attempt to build a telephone interface for a ride sharing system I was working on.
While I was at it, I periodically gave up on the ride sharing project and started a simpler telephone project.
projects that I have been working on use the same core code for interaction with Asterisk PBX.
I decided to clean it all up and put it into a library for my own use and for anyone else who might find it useful.

``Asteramisk`` is based on, or built on top of, the [panoramisk](https://github.com/gawel/panoramisk) library.
It provides a server for handling incoming calls and text messages and a ``Communicator`` class for creating outgoing calls and messaging conversations.
Any communication, both phone calls and text message conversations (and possibly other forms of communication in the future), is represented by a ``UI`` object.
Each form of communication has its own ``UI`` subclass, ``VoiceUI`` for phone calls and ``TextUI`` for text messages.
``UI`` objects provide methods loosely based on the [Twilio](https://www.twilio.com/docs) API, such as ``answer``, ``play``, ``say``, ``gather``, and ``hangup``.

