import tomllib
import unittest

import eyes
from director import Director

CONFIG = tomllib.loads('''
[radar]
far = 4.0
near = 1.0
absence = 4.0
[story]
sleep_sound_every = [10, 10]
scare_cooldown = 20
retrack = 0.3
''')
SOUNDS = ['boo', 'zzz']


class FakeMixer:
    def __init__(self):
        self.played = []

    def play(self, pcm):
        self.played.append(pcm)

    def busy(self):
        return False


class DirectorTest(unittest.TestCase):
    def setUp(self):
        self.player = eyes.Player()
        self.mixer = FakeMixer()
        self.director = Director(CONFIG, self.player, self.mixer, SOUNDS,
                                 choice=lambda options: options[0], uniform=lambda a, b: a)

    def run_story(self, seconds, present=False, distance=None):
        scenes, started = [], None
        for tick in range(int(seconds * 10)):
            self.director.update(tick / 10, present, distance)
            if self.player.started != started:
                started = self.player.started
                scenes.append(self.player.scene)
        return scenes

    def test_absent_plays_the_story(self):
        scenes = self.run_story(150)
        self.assertEqual(scenes[:4], ['sleep', 'sleep', 'wake', 'lurk'])
        self.assertTrue(self.mixer.played, 'ambience sound while asleep')

    def test_arrival_notices_and_tracks(self):
        self.run_story(1)
        scenes = self.run_story(2, present=True, distance=3.0)
        self.assertEqual(self.mixer.played, ['boo'])
        self.assertEqual(scenes, ['track'])

    def test_retrack_only_on_real_movement(self):
        self.director.update(0, True, 3.0)
        started = self.player.started
        self.director.update(1, True, 2.9)
        self.assertEqual(self.player.started, started)
        self.director.update(2, True, 2.5)
        self.assertEqual(self.player.started, 2)

    def test_near_scares_once_per_cooldown(self):
        self.director.update(0, True, 3.0)
        self.director.update(1, True, 0.5)
        self.assertEqual(self.player.scene, 'jumpscare')
        self.director.update(5, True, 0.5)
        self.assertEqual(self.player.scene, 'track')
        self.director.update(22, True, 0.5)
        self.assertEqual(self.player.scene, 'jumpscare')
        self.assertEqual(self.mixer.played, ['boo', 'boo', 'boo'])

    def test_leaving_dozes_after_absence(self):
        self.director.update(0, True, 2.0)
        self.director.update(1, False, None)
        self.assertEqual(self.player.scene, 'track')
        self.director.update(4.5, False, None)
        self.assertEqual(self.player.scene, 'doze')
        self.assertEqual(len(self.mixer.played), 2)
        self.director.update(20, False, None)
        self.assertEqual(self.player.scene, 'sleep')

    def test_unknown_reading_changes_nothing(self):
        self.director.update(0, True, 2.0)
        self.director.update(10, None, None)
        self.assertTrue(self.director.present)


if __name__ == '__main__':
    unittest.main()
