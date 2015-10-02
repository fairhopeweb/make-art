from flask import Flask, Response, request, send_from_directory
import json
import os
import time
import logging

from kano.utils import ensure_dir
from kano_profile.badges import save_app_state_variable_with_dialog, \
    calculate_xp
from kano_profile.apps import load_app_state_variable
from kano_profile.badges import increment_app_state_variable_with_dialog
from kano_world.functions import login_using_token
from kano_world.share import upload_share
from kano.network import is_internet
from kano.utils import play_sound


APP_NAME = 'kano-draw'
PARENT_PID = None

CHALLENGE_DIR = os.path.expanduser('~/Draw-content')
WALLPAPER_DIR = os.path.join(CHALLENGE_DIR, 'wallpapers')

ensure_dir(CHALLENGE_DIR)
ensure_dir(WALLPAPER_DIR)


def _get_static_dir():
    bin_path = os.path.abspath(os.path.dirname(__file__))

    if bin_path.startswith('/usr'):
        return '/usr/share/kano-draw'
    else:
        return os.path.abspath(os.path.join(bin_path, '../www'))

def _get_image_from_str(img_str):
    import base64

    image_b64 = img_str.split(',')[-1]
    image_data = base64.b64decode(image_b64)

    return image_data

def _save(data):
    filename = data['filename']
    try:
        desc = data['description']
    except KeyError:
        desc = ''
    code = data['code']
    image = _get_image_from_str(data['image'])

    filepath = os.path.join(CHALLENGE_DIR, '{}.draw'.format(filename))
    json_path = os.path.join(CHALLENGE_DIR, '{}.json'.format(filename))
    img_path = os.path.join(CHALLENGE_DIR, '{}.png'.format(filename))

    with open(filepath, 'w') as f:
        f.write(code)

    with open(json_path, 'w') as f:
        f.write(
            json.dumps({
                'filename': filename,
                'description': desc
            })
        )

    with open(img_path, 'wb') as f:
        f.write(image)

    return (filename, filepath)


server = Flask(__name__, static_folder=_get_static_dir(), static_url_path='/')
server_logger = logging.getLogger('werkzeug')
server_logger.setLevel(logging.ERROR)


@server.route('/')
# Redirect a localLoad back to index for routing in Angular
@server.route('/localLoad/<path:path>')
def root(path=None):
    return server.send_static_file('index.html')


@server.route('/<path:path>')
def static_proxy(path):
    # send_static_file will guess the correct MIME type
    return server.send_static_file(path)


@server.route("/challenge/local/<path:filename>", methods=['POST'])
def save_challenge(filename):
    data = json.loads(request.data)

    _save(data)

    return ''

@server.route("/challenge/local/<path:path>", methods=['GET'])
def load_challenge(path):
    directory, filename = os.path.split(path)

    return send_from_directory('/{}'.format(directory), filename, as_attachment=True)

@server.route("/challenge/local/wallpaper/<path:filename>", methods=['POST'])
def save_wallpaper(filename):
    data = json.loads(request.data)

    imgs = {
        '1024': _get_image_from_str(data['image_1024']),
        '4-3': _get_image_from_str(data['image_4_3']),
        '16-9': _get_image_from_str(data['image_16_9'])
    }

    img_path = os.path.join(WALLPAPER_DIR,
        '{filename}-{{ratio}}.png'.format(filename=filename))

    for ratio, img_data in imgs.iteritems():
        with open(img_path.format(ratio=ratio), 'wb') as f:
            f.write(img_data)

    return ''

@server.route("/challenge/web/<path:filename>", methods=['POST'])
def share(filename):
    # TODO: Move this connection handling into a function in Kano Utils
    import subprocess

    if not is_internet():
        subprocess.call(['sudo', 'kano-settings', '4'])

    if not is_internet():
        return 'You have no internet'

    success, _ = login_using_token()
    if not success:
        os.system('kano-login 3')
        success, _ = login_using_token()
        if not success:
            return 'Cannot login'

    data = json.loads(request.data)
    filename, filepath = _save(data)
    success, msg = upload_share(filepath, filename, APP_NAME)

    if not success:
        return msg

    increment_app_state_variable_with_dialog(APP_NAME, 'shared', 1)

    return ''

@server.route('/challenge/web', methods=['GET'])
def load_share():
    # TODO: Import kano-share python module and use return code instead
    import subprocess

    p = subprocess.Popen(["kano-share", APP_NAME],
                         stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE)

    for line in p.stdout:
        path = line.split('File Path: ')[-1]
        if len(line) == len(path):
            continue

        path = path.replace('$HOME', os.path.expanduser('~')).rstrip('\n')
        directory, _, filename = path.rpartition('/')

        return send_from_directory(directory, filename, as_attachment=True)


@server.route('/progress/<world>/<int:challengeNo>', methods=['POST'])
def _save_level(world, challengeNo):

    old_xp = calculate_xp()
    needsToSave = False
    

    groups = load_app_state_variable(APP_NAME, 'groups')

    #We might need to load the worlds file here so that we're sure that 
    #noone is abusing the API from the OS
    if groups is None:
        groups = {}


    if world in groups:
        if groups[world]['challengeNo'] < challengeNo:
            groups[world]['challengeNo'] = challengeNo
            needsToSave = True

    else:
        groups[world] = {'challengeNo': challengeNo}
        needsToSave = True

    if needsToSave:
        save_app_state_variable_with_dialog(APP_NAME, 'groups', groups)

    new_xp = calculate_xp()
    return str(new_xp - old_xp)



@server.route('/progress', methods=['GET'])
def _load_level():
    value = {
        'groups': load_app_state_variable(APP_NAME, 'groups'),
        'challenge': load_app_state_variable(APP_NAME, 'challenge')
    }
    #Previously we used to save the progress as "level"
    level = load_app_state_variable(APP_NAME, 'level')
    if (value['groups'] is None):
        value['groups'] = {}


    #Replace the Challege var here.
    if level > value['challenge'] :
        value['challenge'] = level


    value = json.dumps(value)

    return Response(value)
    
    
@server.route('/shutdown', methods=['POST'])
def _shutdown():
    import signal

    # Send signal to parent to initiate shutdown
    os.kill(PARENT_PID, signal.SIGINT)

@server.route('/browsemore', methods=['POST'])
def _browsemore():
    import subprocess

    p = subprocess.Popen(["chromium", "http://world.kano.me/shares/kano-draw"])

@server.errorhandler(404)
def page_not_found(err):
    err_msg = 'Cannot find file {}'.format(request.path)

    return err_msg, 404

@server.route('/play_sound/<path:filename>', methods=['POST'])
def play_sounds(filename):
    print os.path.realpath(os.path.join(_get_static_dir(), filename))
    sound_file = os.path.realpath(os.path.join(_get_static_dir(), filename))
    play_sound(sound_file)

    return ''

def start(parent_pid=None):
    """
    The server process will receive any requests to shutdown but
    the app that runs this as a daemon will be unaware of this
    request so store the PID of the parent.
    """
    global PARENT_PID
    PARENT_PID = parent_pid

    # Run the server
    server.run(port=8000)
    time.sleep(2)
