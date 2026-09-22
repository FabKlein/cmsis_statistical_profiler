define dump_statistical_profile
  if $argc != 1
    echo Usage: dump_statistical_profile output.bin\n
  else
    if statistical_samples.header.complete != 1 || statistical_samples.header.active != 0
      echo Capture is not complete. Stop after sampling_profiler_stop returns.\n
    else
      print statistical_samples.header
      dump binary memory $arg0 &statistical_samples (&statistical_samples+1)
    end
  end
end

document dump_statistical_profile
Dump the finalized statistical_samples object to a binary file.
Usage: dump_statistical_profile output.bin
The target must be halted after sampling_profiler_stop has returned.
AMP: stop both captures before halting; invoke in each core context with its own
ELF and output filename. The same symbol/address may refer to different local RAM.
end
