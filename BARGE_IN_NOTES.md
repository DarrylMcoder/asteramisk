# DTMF barge-in and `stop_speaking()`

## Observed behavior

During a DTMF menu prompt, Asteramisk receives the caller's digit and processes it, but the caller may still hear the entire prompt before the selection appears to take effect.

DTMF collection itself is active during playback: `VoiceUI.gather()` queues the prompt and then waits for input, and `_get_dtmf()` calls `stop_speaking()` when it receives a digit. The problem is therefore in the shared playback interruption path, not in an individual application's menu flow.

## Cause

`VoiceUI.stop_speaking()` clears pending text and the AudioSocket send queue, but it does not cancel the active prompt generation or the current `audconn.write(audio)` operation.

The active writer packetizes the complete synthesized utterance. If `stop_speaking()` empties the send queue while that writer is still running, clearing the queue creates room for the writer to continue adding the remainder of the interrupted prompt. The writer can therefore refill the queue and allow the whole prompt to continue smoothly, rather than producing only a short or choppy tail.

Audio packets that have already been sent to Asterisk or buffered farther downstream in the telephone path cannot be retracted by clearing Asteramisk's local queue. Some residual audio after an interruption must therefore be expected, although downstream buffering alone would not normally explain the complete prompt continuing.

## Fix boundary

The fix belongs in Asteramisk's shared `VoiceUI`/AudioSocket playback layer so every application receives consistent barge-in behavior.

Playback needs a cancellable generation/write boundary. Interrupting an utterance must:

- cancel or invalidate the active generation/write operation;
- prevent any remaining packets from that utterance from being added after the queue is cleared;
- clear pending text and locally queued audio; and
- tolerate the unavoidable short tail of audio already sent downstream.

The implementation should also be protected against races between interruption, queue clearing, and the output worker beginning the next utterance.
