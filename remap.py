
import base64
from contextlib import contextmanager
import copy
from dataclasses import dataclass, field
import os
import pickle
from typing import Any

from imgui_bundle import immapp, hello_imgui, imgui, icons_fontawesome_4
import keyboard
import mouse



@contextmanager
def style_var(var: imgui.StyleVar_, value: float | imgui.ImVec2Like):
    imgui.push_style_var(var, value) # type: ignore
    try:
        yield
    finally:
        imgui.pop_style_var()

@contextmanager
def style_color(col: imgui.Col_, value: imgui.ImVec4Like):
    imgui.push_style_color(col, value)
    try:
        yield
    finally:
        imgui.pop_style_color()

@contextmanager
def disabled(condition: bool = True):
	imgui.begin_disabled(condition)
	try:
		yield
	finally:
		imgui.end_disabled()

@contextmanager
def id(id: Any):
	imgui.push_id(id)
	try:
		yield
	finally:
		imgui.pop_id()



@dataclass
class Bind:
	src: str = ""
	dst: str = ""

@dataclass
class Profile:
	name: str = ""
	binds: list[Bind] = field(default_factory=list)

@dataclass
class State:
	profiles: list[Profile] = field(default_factory=list)
	selected: int = -1



RED = (0.8, 0.2, 0.2, 1)
GREEN = (0.2, 0.8, 0.2, 1)
INVIS = (0, 0, 0, 0)
MOUSE_NAMES = {mouse.LEFT: "mouse1", mouse.RIGHT: "mouse2", mouse.MIDDLE: "mouse3", mouse.X: "mouse4", mouse.X2: "mouse5"}
WHEEL_UP = "wheel up"
WHEEL_DOWN = "wheel down"



state_stack: list[State] = []
state_index = -1

focus_textbox = False
running = False
rebinding = -1


def state() -> State:
	return state_stack[state_index]

def profile() -> Profile:
	return state().profiles[state().selected]

def push_state():
	global state_stack, state_index

	if state_index < -1:
		state_stack = state_stack[:(state_index + 1)]
		state_index = -1

	# Keep top of stack same to avoid breaking saved references within frame
	state_stack.append(state_stack[-1])
	state_stack[-2] = copy.deepcopy(state_stack[-1])

def change_state(offset: int):
	global state_index
	state_index = max(-len(state_stack), min(state_index + offset, -1))

def send_input(key: str, press: bool):
	if key == WHEEL_UP:
		if press:
			mouse.wheel(1)
	elif key == WHEEL_DOWN:
		if press:
			mouse.wheel(-1)
	elif key in MOUSE_NAMES.values():
		button = next(key for key, val in MOUSE_NAMES.items() if val == key)
		if press:
			mouse.press(button)
		else:
			mouse.release(button)
	else:
		if press:
			keyboard.press(key)
		else:
			keyboard.release(key)

def remap_input(src, dst):
	if src in MOUSE_NAMES.values() or src == WHEEL_UP or src == WHEEL_DOWN:
		def mouse_handler(e):
			if isinstance(e, mouse.MoveEvent):
				return

			if isinstance(e, mouse.WheelEvent):
				if (src == WHEEL_UP and e.delta > 0) or (src == WHEEL_DOWN and e.delta < 0):
					send_input(dst, True)
					send_input(dst, False)
				return

			if MOUSE_NAMES[e.button] != src:
				return
			
			if e.event_type != mouse.UP:
				send_input(dst, True)
			else:
				send_input(dst, False)
		
		mouse.hook(mouse_handler)
	else:
		def key_handler(e):
			if e.event_type == 'down':
				send_input(dst, True)
			elif e.event_type == 'up':
				send_input(dst, False)
			return False

		keyboard.hook_key(src, key_handler, suppress=True)

def binding_entered(binding: str):
	global rebinding

	bind = profile().binds[rebinding]

	if bind.src == "":
		bind.src = binding
		return
	
	assert bind.dst == ""

	bind.dst = binding

	rebinding = -1
	keyboard.unhook(keyboard_callback)
	mouse.unhook(mouse_callback)

def keyboard_callback(ke: keyboard.KeyboardEvent):
	if ke.event_type != 'down':
		return

	assert ke.name is not None
	
	binding_entered(ke.name.lower())

def mouse_callback(e):
	if isinstance(e, mouse.MoveEvent):
		return

	if isinstance(e, mouse.WheelEvent):
		binding_entered("wheel up" if e.delta > 0 else "wheel down")
		return
	
	if e.event_type == mouse.UP:
		return

	binding_entered(MOUSE_NAMES[e.button])

def trash_button() -> bool:
	with style_var(imgui.StyleVar_.frame_border_size, 0):
		with style_color(imgui.Col_.button, INVIS):
			with style_color(imgui.Col_.text, RED):
				return imgui.button(icons_fontawesome_4.ICON_FA_TRASH)

def gui():
	global focus_textbox, running, rebinding

	with id(state().selected):
		with disabled(rebinding != -1):
			with disabled(running):
				with disabled(state().selected == -1):
					if state().selected == -1:
						imgui.input_text("##Name", "")
					else:
						if focus_textbox:
							imgui.set_keyboard_focus_here()
							focus_textbox = False
						# Need to add undo/redo support for this
						_, profile().name = imgui.input_text("##Name", profile().name)

				imgui.same_line(0, 0)

				if imgui.begin_combo("##Profile", profile().name if state().selected != -1 else "", imgui.ComboFlags_.no_preview | imgui.ComboFlags_.popup_align_left):
					for n in range(len(state().profiles)):
						with id(n):
							is_selected = (state().selected == n)
							clicked, is_selected = imgui.selectable(state().profiles[n].name, is_selected)
							if is_selected:
								state().selected = n
							if clicked:
								focus_textbox = True
					if imgui.selectable("<new>", False)[0]:
						push_state()
						state().selected = len(state().profiles)
						num = 1
						while True:
							new_name = f"Profile {num}"
							if not any(profile.name == new_name for profile in state().profiles):
								state().profiles.append(Profile(new_name))
								break
							num += 1
						focus_textbox = True

					imgui.end_combo()

				imgui.same_line(0, 4)

				with disabled(state().selected == -1):
					if trash_button():
						push_state()
						state().profiles.pop(state().selected)
						if state().selected != 0 or len(state().profiles) == 0:
							state().selected -= 1

				imgui.spacing()
				imgui.separator()
				imgui.spacing()

				BIND_BUTTON_SIZE = (135, 0)

				if imgui.begin_child("body", (0, -(imgui.get_frame_height() + imgui.get_style().item_spacing.y))):
					if state().selected != -1:
						binds = profile().binds
						i = 0
						while i < len(binds):
							with id(len(binds) - i):
								if imgui.button(f"{binds[i].src} → {binds[i].dst}", BIND_BUTTON_SIZE):
									push_state()
									binds[i].src = ""
									binds[i].dst = ""
									rebinding = i
									keyboard.hook(keyboard_callback)
									mouse.hook(mouse_callback)
								imgui.same_line(0, 4)
								if trash_button():
									push_state()
									del binds[i]
									continue
								i += 1

						if imgui.button("<new>", BIND_BUTTON_SIZE):
							push_state()
							rebinding = len(binds)
							binds.append(Bind())
							keyboard.hook(keyboard_callback)
							mouse.hook(mouse_callback)

					imgui.end_child()

			with disabled(state().selected == -1):
				with style_color(imgui.Col_.text, RED if running else GREEN):
					if imgui.button(icons_fontawesome_4.ICON_FA_STOP if running else icons_fontawesome_4.ICON_FA_PLAY, (imgui.get_content_region_avail().x, 0)):
						running = not running
						if running:
							for bind in profile().binds:
								remap_input(bind.src, bind.dst)
						else:
							keyboard.unhook_all()
							mouse.unhook_all()

	if imgui.get_io().key_ctrl and imgui.is_key_pressed(imgui.Key.z):
		change_state(-1)
		
	if imgui.get_io().key_ctrl and imgui.is_key_pressed(imgui.Key.y):
		change_state(1)



def load_settings():
	global state_stack

	if data := hello_imgui.load_user_pref("state"):
		state_stack.append(pickle.loads(base64.b64decode(data)))
	else:
		state_stack.append(State())

def load_fonts():
	hello_imgui.load_font_ttf_with_font_awesome_icons(os.path.join(os.environ["WINDIR"], "Fonts", "segoeui.ttf"), 16)

def save_settings():
	# Prevents saving incomplete binds. Would be better to not write these to state, but then UI is annoying
	if state().selected != -1:
		profile().binds = [bind for bind in profile().binds if bind.dst]

	hello_imgui.save_user_pref("state", base64.b64encode(pickle.dumps(state())).decode("ascii"))

if __name__ == "__main__":
	params = hello_imgui.RunnerParams()
	params.app_window_params.window_title = "ReMap"
	params.app_window_params.window_geometry.size = (176, 300)
	params.callbacks.post_init = load_settings
	params.callbacks.load_additional_fonts = load_fonts
	params.callbacks.before_exit = save_settings
	params.callbacks.show_gui = gui

	immapp.run(params)
