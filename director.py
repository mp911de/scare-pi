"""Decides what the eyes do and which sound plays, from presence and distance.

Absent: the story loop (eyes.STORY) with a sound now and then while asleep.
Present: a sound on arrival, eyes track the visitor; closer than `near` triggers one
jumpscare with a sound, then a cooldown. Absence for `absence` seconds plays a
sound and sends the eyes dozing back into the story. Every sound moment picks a
random file from one pool. Pure logic: time comes in through `now`, sounds go out
through the mixer.
"""
import random

import eyes


class Director:
    def __init__(self, config, player, mixer, sounds, choice=random.choice, uniform=random.uniform):
        self.radar, self.story = config['radar'], config['story']
        self.player, self.mixer, self.sounds = player, mixer, sounds
        self.choice, self.uniform = choice, uniform
        self.present = False
        self.last_seen = None
        self.last_scare = float('-inf')
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
        self.play()

    def attend(self, now, distance):
        if self.player.scene == 'jumpscare' and not self.player.done(now):
            return
        if distance <= self.radar['near'] and now - self.last_scare >= self.story['scare_cooldown']:
            self.last_scare = now
            self.player.start('jumpscare', now)
            self.play()
            return
        if self.tracked is None or abs(distance - self.tracked) >= self.story['retrack']:
            self.tracked = distance
            self.player.start('track', now, distance)

    def leave(self, now):
        self.present = False
        self.play()
        self.player.start('doze', now)
        self.story_at = eyes.STORY.index('sleep')

    def idle(self, now):
        if self.player.done(now):
            self.player.start(eyes.STORY[self.story_at], now)
            self.story_at = (self.story_at + 1) % len(eyes.STORY)
        if self.player.scene == 'sleep':
            if self.next_sleep_sound is None:
                self.next_sleep_sound = now + self.uniform(*self.story['sleep_sound_every'])
            elif now >= self.next_sleep_sound and not self.mixer.busy():
                self.next_sleep_sound = None
                self.play()

    def play(self):
        if self.sounds:
            self.mixer.play(self.choice(self.sounds))
