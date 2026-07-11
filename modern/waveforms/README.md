# ZS407 waveform programs

`tools/compile-waveform.py` converts a line-oriented program into the portable
`ZSAW/1` event format. Compilation is a Mac/host operation: it never contacts
the analyzer and never enables an output.

```text
at 0us gate off
at 0us frequency 100MHz
at 0us level -30.0dBm
at 1ms gate on
at 11ms gate off
at 11ms end
```

Time units are `us`, `ms` and `s`; frequency units are `Hz`, `kHz`, `MHz` and
`GHz`. Levels are in `dBm` with 0.1 dB representability. `dac 0..4095` and
`wait-trigger` are also legal actions.

The compiler enforces monotonic time, an initial output-off event, trigger waits
only while gated off, and a final output-off `end`. These are necessary program
invariants, not RF-safety certification. The format is a 12-byte little-endian
header (`ZSAW`, version, 16-byte event size, count, payload CRC-32) followed by
fixed 16-byte events matching `zs407_wave_event_t`.

Compile and inspect the checked-in fixture:

```bash
tools/compile-waveform.py tests/fixtures/safe_burst.zsaw.txt \
  -o .artifacts/safe_burst.zsaw
tools/compile-waveform.py --inspect .artifacts/safe_burst.zsaw
```

Phase 5 does not contain an uploader or an event executor. This format is the
tested contract for those later pieces; the only embedded waveform backend is
the separately locked low-frequency DAC buffer.
