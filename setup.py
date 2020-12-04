from setuptools import setup
import io


with io.open('README.org', encoding='utf-8') as f:
    long_description = f.read()

with io.open('requirements.txt', encoding='utf-8') as f:
    requirements = [r for r in f.read().split('\n') if len(r)]

setup(name='lntopo',
      version='0.1.0',
      description='Tools to work with lnresearch/topology datasets',
      long_description=long_description,
      long_description_content_type='text/x-org',
      url='http://github.com/lnresearch/topology',
      author='Christian Decker',
      author_email='decker.christian@gmail.com',
      license='MIT',
      packages=[],
      package_data={},
      scripts=[],
      zip_safe=True,
      entry_points = {
          'console_scripts': [
              'lntopo-cli = cli.__main__:cli',
          ],
      },
      install_requires=requirements
)
