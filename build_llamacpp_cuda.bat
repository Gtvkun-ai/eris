@echo off
REM Build llama-cpp-python==0.3.16 voi CUDA cho GTX 1650 Ti (compute 7.5), CUDA Toolkit 12.6.
REM Pin 0.3.16: ban CPU dang chay la 0.3.16 va da chay qwen3 OK; tarball cu khong dinh long-path.
if not exist C:\t mkdir C:\t
set TMP=C:\t
set TEMP=C:\t
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
set CMAKE_ARGS=-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=75 -DCMAKE_CUDA_FLAGS=-allow-unsupported-compiler
set FORCE_CMAKE=1
python -m pip install llama-cpp-python==0.3.16 --force-reinstall --no-cache-dir --no-binary llama-cpp-python
echo BUILD_EXIT=%ERRORLEVEL%
