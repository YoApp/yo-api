from __future__ import with_statement
from fabric.api import *
from contextlib import contextmanager as _contextmanager
import requests

env.user = 'ubuntu'
env.directory = '/home/ubuntu/api'
env.use_ssh_config = True
env.activate = 'source /home/ubuntu/api/env/bin/activate'

env.hosts = ['54.165.58.118',  # web

             '54.82.185.132',  # workerlow
             '54.165.68.153',
             #'54.174.243.133',

             #'54.152.62.193',  # workermedium
             #'54.164.255.126',

             #'54.210.148.202',  # workerhigh
             #'54.210.150.26'
             ]


@_contextmanager
def virtualenv():
    with cd(env.directory):
        with prefix(env.activate):
            yield


@parallel
def deploy():
    with virtualenv():
        run('git pull')
        run('echo $PATH')
        run('pip install -r requirements.txt')
        run('sudo service supervisor restart')
        #requests.post('https://yohooks.com/justyo/or/',
        #              json={
        #                 'text': 'deployed'
        #              })