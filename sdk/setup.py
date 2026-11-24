"""Install the matching prebuilt SDK and inference helpers without compiling an engine."""
import platform
from pathlib import Path
import shutil
from setuptools import setup, Distribution
from setuptools.command.build_py import build_py
ROOT=Path(__file__).resolve().parent
class NativeDistribution(Distribution):
    def has_ext_modules(self):return True
class BuildSDK(build_py):
    def run(self):
        if platform.system()!='Linux' or platform.machine().lower() not in ('aarch64','arm64'):
            raise RuntimeError('This prebuilt SDK requires Linux AArch64')
        library=ROOT/'lib/libcosyvoice3.so'
        if not library.is_file():raise RuntimeError('Stage the matching prebuilt SDK in sdk/lib before installation')
        super().run()
        root=Path(self.build_lib)/'pandora_fun_cosyvoice3_0_5b_2512'/'_cosyvoice3_runtime';target=root/'lib';target.mkdir(parents=True,exist_ok=True)
        shutil.copy2(library,target/library.name)
        shutil.copytree(ROOT/'lib/qnn248',target/'qnn248',dirs_exist_ok=True)
        for name in ('LICENSE','LICENSE.zh-CN.txt','THIRD_PARTY_NOTICES.txt','THIRD_PARTY_LICENSES.txt','LICENSES'):
            source=ROOT/'lib'/name
            if not source.exists():raise RuntimeError('Missing SDK legal material: '+name)
            if source.is_dir():shutil.copytree(source,target/name,dirs_exist_ok=True)
            else:shutil.copy2(source,target/name)
        shutil.copytree(ROOT/'third_party/wetext', root/'licenses/wetext', dirs_exist_ok=True)
        (root/'assets').mkdir(exist_ok=True)
        shutil.copytree(ROOT/'assets',root/'assets',dirs_exist_ok=True)
setup(package_dir={'':'python'},packages=['pandora_fun_cosyvoice3_0_5b_2512', 'pandora_fun_cosyvoice3_0_5b_2512._cosyvoice3_runtime'],
      cmdclass={'build_py':BuildSDK},distclass=NativeDistribution)
