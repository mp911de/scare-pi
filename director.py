"""Decides what the eyes do and which sound plays, from presence and distance.

Absent: the story loop (eyes.STORY) with a sound now and then while asleep.
Present: a sound on arrival, eyes track the visitor; closer than `near` triggers one
jumpscare with a sound, then a cooldown. Sounds come at most every `sound_every` seconds. Absence for `absence` seconds plays a
sound and sends the eyes dozing back into the story. Every sound moment picks a
random file from one pool. The easter egg replaces a lurk now and then with the
kitt scanner and its own sound. Pure logic: time comes in through `now`, sounds go out
through the mixer.
"""
import random

import eyes


class Director:
    def __init__(self, config, player, mixer, sounds, egg=None, choice=random.choice, uniform=random.uniform):
        self.radar, self.story = config['radar'], config['story']
        self.player, self.mixer, self.sounds = player, mixer, sounds
        self.egg, self.egg_chance = egg, config.get('easter_egg', {}).get('chance', 0)
        self.choice, self.uniform = choice, uniform
        self.present = False
        self.last_seen = None
        self.last_scare = self.last_sound = float('-inf')
        self.tracked = None
        self.story_at = 0
        self.next_sleep_sound = None

    def update(self, now, present, distance):
        if present and distance <= self.radar['far']:
            self.last_seen = now
            if not self.present:
                self.arrive(now)
            self.attend(now, distance)
        elif self.present and present is False and now - self.last_seen >= self.radar['absence']:
            self.leave(now)
        elif not self.present:
            self.idle(now)

    def arrive(self, now):
        self.present = True
        self.tracked = None
        self.play(now)

    def attend(self, now, distance):
        if self.player.scene == 'jumpscare' and not self.player.done(now):
            return
        if distance <= self.radar['near'] and now - self.last_scare >= self.story['scare_cooldown']:
            self.last_scare = now
            self.player.start('jumpscare', now)
            self.play(now)
            return
        if self.tracked is None or abs(distance - self.tracked) >= self.story['retrack']:
            self.tracked = distance
            self.player.start('track', now, distance)

    def leave(self, now):
        self.present = False
        self.play(now)
        self.player.start('doze', now)
        self.story_at = eyes.STORY.index('sleep')

    def idle(self, now):
        if self.player.done(now):
            scene = eyes.STORY[self.story_at]
            self.story_at = (self.story_at + 1) % len(eyes.STORY)
            if scene == 'lurk' and self.egg and self.uniform(0, 1) < self.egg_chance \
                    and self.play(now, self.egg):  # the scanner only with its chime
                self.player.start('kitt', now)
                return
            self.player.start(scene, now)
        if self.player.scene == 'sleep':
            if self.next_sleep_sound is None:
                self.next_sleep_sound = now + self.uniform(*self.story['sleep_sound_every'])
            elif now >= self.next_sleep_sound and not self.mixer.busy():
                self.next_sleep_sound = None
                self.play(now)

    def play(self, now, pcm=None):
        """One sound per `sound_every` seconds, so nothing cuts a sound short or nags."""
        if now - self.last_sound < self.story['sound_every'] or not (pcm or self.sounds):
            return False
        self.last_sound = now
        self.mixer.play(pcm or self.choice(self.sounds))
        return True
