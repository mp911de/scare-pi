# Runs where invoked: on the Mac for model tests, on the Pi for hardware.
test:
	python3 -m unittest discover -p 'test_*.py'

sync:
	mutagen sync flush scare-pi

.PHONY: test sync
