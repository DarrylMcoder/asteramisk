import os
from setuptools import setup, find_packages

# Get the long description from the README file
here = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(here, 'docs', 'index.rst')) as f:
    long_description = f.read()

setup(
    name='asteramisk',
    version='0.1.0',
    author='Darryl Martin',
    author_email='darryl9829@gmail.com',
    description='Python library providing TWILIO-like voice and messaging APIs with Asterisk backend',
    long_description=long_description,
    long_description_content_type='text/x-rst',
    url='https://github.com/DarrylMcoder/asteramisk',
    packages=find_packages(),
    python_requires='>=3.6',
    install_requires=[
        'aioari @ git+https://github.com/M-o-a-T/aioari.git@f892ae7e3ea0832e8a4728383135008cb58a792f',
        'aiofiles==24.1.0',
        'aiolimiter==1.2.1',
        'google-cloud-speech==2.33.0',
        'google-cloud-texttospeech==2.27.0',
        'gTTS==2.5.4',
        'openai-agents==0.2.9',
        'panoramisk==1.4',
        'pydub==0.25.1',
        'setuptools'
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent"
    ]
)
