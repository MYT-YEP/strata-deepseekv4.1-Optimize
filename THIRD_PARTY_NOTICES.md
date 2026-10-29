# Third-party sources and licenses

This project is an independent integration. No affiliation or endorsement is implied.

- [Strata / Xolotl](https://github.com/Indras-Mirror/Xolotl), pinned commit `684e3c0693cdb1d928aea525175ef30df9f6ec84`: MIT. `patches/xolotl-local-dspark.patch` contains modifications and upstream context. See [Xolotl license](licenses/Xolotl-MIT.txt).
- [llama.cpp](https://github.com/ggml-org/llama.cpp), pinned commit `6050b467c07a95c7b87debd4ddac2f8ba8d9b807`: MIT. `patches/llama-ggml.patch` includes the project's required ggml modifications and upstream context. See [llama.cpp license](licenses/llama.cpp-MIT.txt).
- [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness), `@deepseek-ai/dsh` 0.2.1-rc.2: MIT. The repository includes local profile configuration and an npm lockfile, not the installed package. See [Harness license](licenses/deepseek-harness-MIT.txt); individual npm dependencies retain their own licenses.
- Model files and tokenizer/pack metadata derive from the pinned [ISTA-DASLab GGUF repository](https://huggingface.co/ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF) and [Unsloth GGUF repository](https://huggingface.co/unsloth/DeepSeek-V4.1-Flash-1017-GGUF); their model cards identify MIT licenses. The underlying model and any separately downloaded files remain subject to the upstream terms. **Model weights are not included here.**
- The precomputed expert-rank file is a converted profile snapshot needed to reproduce this setup. Its SHA-256 is recorded in `reproduction/manifest.json`; it is not a model-weight file.
- CUDA Toolkit redistributables, Node.js, Visual Studio tooling and the Strata release archives are not distributed in this repository. Obtain them from their respective publishers and review their licenses.
- Pelican prompt attributed to [Simon Willison](https://simonwillison.net/2024/Oct/25/pelicans-on-a-bicycle/); the rendered image and JSON in this repository are the locally generated sample, not a copied leaderboard result.
