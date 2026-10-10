"""Package the original closed control release; no generated runtime policy."""
from pathlib import Path
from setuptools.command.build_py import build_py

TOP_FILES = ('model_policy.yaml', 'bootstrap.py', 'pyproject.toml', 'requirements.lock')


class ControlBuild(build_py):
    def run(self):
        super().run()
        root = Path(__file__).resolve().parent
        for name in TOP_FILES:
            source = root / name
            if source.is_symlink() or not source.is_file():
                raise ValueError('original regular control release input required')
            self.copy_file(str(source), str(Path(self.build_lib) / name))

    def get_outputs(self, include_bytecode=1):
        return super().get_outputs(include_bytecode) + [str(Path(self.build_lib) / name) for name in TOP_FILES]
