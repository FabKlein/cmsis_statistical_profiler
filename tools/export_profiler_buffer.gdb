define export_profiler_buffer
  if $argc != 1
    echo Usage: export_profiler_buffer output.bin\n
  else
    if statistical_samples.header.complete != 1 || statistical_samples.header.active != 0
      echo Capture is not complete. Stop after sampling_profiler_stop returns.\n
    else
      print statistical_samples.header
      dump binary memory $arg0 &statistical_samples (&statistical_samples+1)
    end
  end
end

document export_profiler_buffer
Export the finalized statistical_samples buffer to a binary file on the host.
Usage: export_profiler_buffer output.bin
The target must be halted after sampling_profiler_stop has returned.
header.bytes_used counts committed record bytes; records may have variable length.
Export the whole allocation so the decoder can validate buffer dimensions.
AMP: stop both captures before halting; invoke in each core context with its own
ELF and output filename. The same symbol/address may refer to different local RAM.
end
