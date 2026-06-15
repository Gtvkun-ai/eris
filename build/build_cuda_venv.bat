@echo off
REM Build llama-cpp-python==0.3.28 (= ban dang cai) voi CUDA cho GTX 1650 Ti (compute 7.5),
REM CUDA Toolkit 12.6, cai THANG vao venv 3.14 cua repo.
setlocal
set "VENV_PY=C:\Users\Gtvkun\Documents\GitHub\eris\.venv\Scripts\python.exe"
if not exist C:\t mkdir C:\t
set TMP=C:\t
set TEMP=C:\t
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
set "CMAKE_ARGS=-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=75 -DCMAKE_CUDA_FLAGS=-allow-unsupported-compiler"
set FORCE_CMAKE=1
echo === Building llama-cpp-python 0.3.28 CUDA into venv ===
"%VENV_PY%" -m pip install llama-cpp-python==0.3.28 --force-reinstall --no-cache-dir --no-binary llama-cpp-python
echo BUILD_EXIT=%ERRORLEVEL%
echo === Verify GPU offload ===
"%VENV_PY%" -c "from llama_cpp import llama_cpp as L; print('supports_gpu_offload:', L.llama_supports_gpu_offload())"
