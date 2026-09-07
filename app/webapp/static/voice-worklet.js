/* task-os — the microphone tap behind the live transcript (#146).
 *
 * All this does is hand the main thread a copy of every block of samples the
 * audio graph produces. It is an `AudioWorkletProcessor` rather than the
 * (deprecated) `ScriptProcessorNode` for the ordinary reason: audio callbacks
 * run on the audio thread, where a busy main thread cannot make them drop
 * samples — and dropping samples mid-sentence is exactly the failure this
 * feature would be blamed for.
 *
 * **Why raw samples rather than a recording.** The live transcript needs a
 * *decodable snapshot mid-take*, and a MediaRecorder container cut off
 * mid-stream is not reliably decodable — iOS Safari's fragmented mp4 certainly
 * is not. Float32 blocks have no container to truncate: `voice.js` concatenates
 * whatever it has so far and encodes a complete WAV from it at any moment.
 * That is also why `MediaRecorder` and `decodeAudioData` are no longer in the
 * pipeline at all.
 *
 * Channel 0 only: `voice.js` asks for a mono capture, and a phone's second
 * channel is the same voice twice.
 */

class VoiceTap extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    // A disconnected or not-yet-flowing input gives an empty block. Say
    // nothing rather than posting a zero-length frame the other side would
    // have to filter.
    if (channel && channel.length) {
      // `channel` is reused by the audio thread on the next call, so the copy
      // is not optional — posting the view itself would send whatever the
      // buffer holds by the time it is read.
      this.port.postMessage(new Float32Array(channel));
    }
    return true;                    // keep the node alive until it is dropped
  }
}

registerProcessor('voice-tap', VoiceTap);
