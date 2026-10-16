@echo off
set MATLENS_HOME=%USERPROFILE%\.matlens
echo === MatLens Logo 像素画预览（请全屏/宽终端查看）===
"C:/Users/22091/.workbuddy/binaries/python/envs/matlens2/Scripts/python.exe" -c "import sys,os; sys.path.insert(0, r'D:/MatLens'); os.environ['MATLENS_HOME']=os.path.expanduser('~/.matlens'); from matlens_cli.banner import _matlens_logo_renderable; from rich.console import Console; r=_matlens_logo_renderable(54); Console(color_system='truecolor').print(r) if r else print('Logo 未生成')"
pause
