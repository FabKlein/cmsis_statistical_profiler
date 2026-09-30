# Documentation scaffold

Early draft, following the CMSIS-NN `Doxygen/src` layout. APIs and text are evolving.
The [repository README](../README.md) and [integration guide](../docs/INTEGRATION.md)
remain the detailed references.

With Doxygen installed, run from the repository root:

```sh
bash Documentation/Doxygen/gen_doc.sh
```

Open `Documentation/html/index.html`. Generated HTML is ignored by Git.
Edit `Doxygen/src/mainpage.md` for the introduction and `mcu/*.h` for API comments.
