
import base64
from contextlib import contextmanager
import copy
from dataclasses import dataclass, field
import os
import pickle
import threading
import time
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
def push_id(id: Any):
	imgui.push_id(id)
	try:
		yield
	finally:
		imgui.pop_id()



@dataclass
class Bind:
	src: str = ""
	dst: str = ""
	spam: float = -1
	toggle: bool = False

@dataclass
class Profile:
	name: str = ""
	binds: list[Bind] = field(default_factory=list)

@dataclass
class State:
	profiles: list[Profile] = field(default_factory=list)
	selected: int = -1



RED = (0.8, 0.3, 0.3, 1)
GREEN = (0.3, 0.7, 0.3, 1)
DIM_GREEN = (0.1, 0.3, 0.1, 1)
INVIS = (0, 0, 0, 0)
MOUSE_NAMES = {mouse.LEFT: "mouse1", mouse.RIGHT: "mouse2", mouse.MIDDLE: "mouse3", mouse.X: "mouse4", mouse.X2: "mouse5"}
WHEEL_UP = "wheel up"
WHEEL_DOWN = "wheel down"



state_stack: list[State] = []
state_index = -1

# Should consider using a state machine for this. Three states? Idle, Binding, Running

rebinding = -1
running = False

focus_textbox = False

pressed_binds: list[Bind] = []
bind_threads: dict[int, threading.Event] = {}



def is_mouse(key: str):
	return key in MOUSE_NAMES.values() or key == WHEEL_DOWN or key == WHEEL_UP

def state() -> State:
	return state_stack[state_index]

def profile() -> Profile:
	return state().profiles[state().selected]

def ensure_push_state():
	global state_stack, state_index

	if state_index < -1:
		state_stack = state_stack[:(state_index + 1)]
		state_index = -1

	# Compare only profiles here since we don't consider state.selected as a real edit
	if len(state_stack) == 1 or state_stack[-2].profiles != state_stack[-1].profiles:
		# Preserve top of stack to avoid breaking saved references within frame
		state_stack.append(state_stack[-1])
		state_stack[-2] = copy.deepcopy(state_stack[-1])

def change_state(offset: int):
	global state_index
	state_index = max(-len(state_stack), min(state_index + offset, -1))

def send_input(key: str, press: bool):
	if not is_mouse(key):
		if press:
			keyboard.press(key)
		else:
			keyboard.release(key)
		return
	
	if key == WHEEL_UP:
		if press:
			mouse.wheel(1)
	elif key == WHEEL_DOWN:
		if press:
			mouse.wheel(-1)
	else:
		button = next(k for k, v in MOUSE_NAMES.items() if v == key)
		if press:
			mouse.press(button)
		else:
			mouse.release(button)

def spam_input(key: str, interval: float, stop_event: threading.Event):
	while not stop_event.is_set():
		send_input(key, True)
		send_input(key, False)
		time.sleep(interval)

def on_key(bind: Bind, press: bool):
	if bind.toggle:
		toggled = any(b is bind for b in pressed_binds)
		pressed = press and not toggled
		released = press and toggled
	else:
		pressed = press
		released = not press

	if pressed:
		if bind.spam == -1:
			send_input(bind.dst, True)
		else:
			stop_event = threading.Event()
			bind_threads[id(bind)] = stop_event
			threading.Thread(target=spam_input, args=(bind.dst, bind.spam, stop_event)).start()
		pressed_binds.append(bind)
	elif released:
		if bind.spam == -1:
			send_input(bind.dst, False)
		else:
			bind_threads[id(bind)].set()
			del bind_threads[id(bind)]
		pressed_binds.remove(bind)

def remap_input(bind: Bind):
	if is_mouse(bind.src):
		def mouse_handler(e):
			if isinstance(e, mouse.MoveEvent):
				return

			if isinstance(e, mouse.WheelEvent):
				if (bind.src == WHEEL_UP and e.delta > 0) or (bind.src == WHEEL_DOWN and e.delta < 0):
					on_key(bind, True)
					on_key(bind, False)
				return

			if MOUSE_NAMES[e.button] != bind.src:
				return
			
			if e.event_type != mouse.UP:
				on_key(bind, True)
			else:
				on_key(bind, False)
		
		mouse.hook(mouse_handler)
	else:
		last_state = None
		binds = profile().binds
		is_last_bind_for_key = not any(bind.src == b.src for b in binds[binds.index(bind) + 1:])

		def key_handler(e):
			nonlocal last_state

			if e.event_type != last_state:
				if e.event_type == keyboard.KEY_DOWN:
					on_key(bind, True)
				elif e.event_type == keyboard.KEY_UP:
					on_key(bind, False)

				last_state = e.event_type

			# Return value is "should we let input pass through"
			return not is_last_bind_for_key

		keyboard.hook_key(bind.src, key_handler, suppress=True)

def start_rebinding(bind: int):
	profile().binds[bind].src = ""
	profile().binds[bind].dst = ""

	global rebinding
	rebinding = bind

	keyboard.hook(keyboard_callback)
	mouse.hook(mouse_callback)

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

TRASH_BUTTON_SIZE = (24, 0)

def trash_button() -> bool:
	with style_var(imgui.StyleVar_.frame_border_size, 0):
		with style_color(imgui.Col_.button, INVIS):
			with style_color(imgui.Col_.text, RED):
				return imgui.button(icons_fontawesome_4.ICON_FA_TRASH, TRASH_BUTTON_SIZE)

def colored_dummy(size: imgui.ImVec2Like, color: imgui.ImVec4Like):
	p_min = imgui.get_cursor_screen_pos()
	p_max = imgui.ImVec2(p_min.x + size[0], p_min.y + size[1])

	imgui.get_window_draw_list().add_rect_filled(p_min, p_max, imgui.get_color_u32(color), imgui.get_style().frame_rounding)

	imgui.dummy(size)

def gui():
	global focus_textbox, running, pressed_binds, bind_threads

	with push_id(state().selected):
		with disabled(rebinding != -1):
			with disabled(running):
				DROPDOWN_SPACING = 0
				DROPDOWN_BUTTON_WIDTH = imgui.get_frame_height()
				TRASH_SPACING = 2

				PROFILE_TEXT_BOX_WIDTH = imgui.get_content_region_avail().x - DROPDOWN_SPACING - DROPDOWN_BUTTON_WIDTH - TRASH_SPACING - TRASH_BUTTON_SIZE[0]

				with disabled(state().selected == -1):
					if state().selected == -1:
						imgui.input_text("##Name", "")
					else:
						if focus_textbox:
							imgui.set_keyboard_focus_here()
							focus_textbox = False

						imgui.set_next_item_width(PROFILE_TEXT_BOX_WIDTH)

						_, profile().name = imgui.input_text("##Name", profile().name)
						if imgui.is_item_activated():
							ensure_push_state()

				imgui.same_line(0, DROPDOWN_SPACING)

				if imgui.begin_combo("##Profile", profile().name if state().selected != -1 else "", imgui.ComboFlags_.no_preview | imgui.ComboFlags_.popup_align_left):
					for n in range(len(state().profiles)):
						with push_id(n):
							is_selected = (state().selected == n)
							clicked, is_selected = imgui.selectable(state().profiles[n].name, is_selected)
							if is_selected:
								# We don't ensure_push_state for this because we don't consider it an edit. However it does get carried
								#  along with undos, which is good because then it shows the relevant profiles
								state().selected = n
							if clicked:
								focus_textbox = True

					if imgui.selectable("<new>", False)[0]:
						ensure_push_state()
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

				imgui.same_line(0, TRASH_SPACING)

				with disabled(state().selected == -1):
					if trash_button():
						ensure_push_state()

						state().profiles.pop(state().selected)

						if state().selected != 0 or len(state().profiles) == 0:
							state().selected -= 1

				imgui.spacing()
				imgui.separator()
				imgui.spacing()

				if imgui.begin_child("body", (0, -(imgui.get_frame_height() + imgui.get_style().item_spacing.y))):
					if state().selected != -1:
						LIGHT_SIZE = (6, imgui.get_frame_height())
						LIGHT_SPACING = 4
						OPTIONS_SPACING = 2
						OPTIONS_BUTTON_SIZE = (24, 0)
						TRASH_SPACING = 0

						BIND_BUTTON_SIZE = (imgui.get_content_region_avail().x - LIGHT_SIZE[0] - LIGHT_SPACING - OPTIONS_SPACING - OPTIONS_BUTTON_SIZE[0] - TRASH_SPACING - TRASH_BUTTON_SIZE[0], 0)

						binds = profile().binds

						i = 0
						while i < len(binds):
							with push_id(len(binds) - i):
								colored_dummy(LIGHT_SIZE, GREEN if any(b is binds[i] for b in pressed_binds) else DIM_GREEN)

								imgui.same_line(0, LIGHT_SPACING)

								if imgui.button(f"{binds[i].src} → {binds[i].dst}", BIND_BUTTON_SIZE):
									ensure_push_state()
									start_rebinding(i)
								if is_mouse(binds[i].src):
									imgui.set_item_tooltip("NOTE: Mouse inputs have no input suppression")

								imgui.same_line(0, OPTIONS_SPACING)

								with style_var(imgui.StyleVar_.frame_border_size, 0):
									with style_color(imgui.Col_.button, INVIS):
										mode = "R" if binds[i].spam == -1 else "S"
										if binds[i].toggle:
											mode += "T"

										if imgui.button(mode, OPTIONS_BUTTON_SIZE):
											imgui.open_popup("options")

								if imgui.begin_popup("options"):
									is_spam = (binds[i].spam != -1)
									clicked, is_spam = imgui.checkbox("Spam", is_spam)
									if clicked:
										ensure_push_state()
										if is_spam:
											binds[i].spam = 0.1
										else:
											binds[i].spam = -1
									if is_spam:
										imgui.same_line()
										imgui.set_next_item_width(100)
										changed, interval = imgui.slider_float("##", binds[i].spam, 0, 10, "%.4fs", imgui.SliderFlags_.logarithmic)
										if imgui.is_item_activated():
											ensure_push_state()
										if changed:
											binds[i].spam = interval

									clicked, is_toggle = imgui.checkbox("Toggle", binds[i].toggle)
									if clicked:
										ensure_push_state()
										binds[i].toggle = is_toggle

									imgui.end_popup()
									
								imgui.same_line(TRASH_SPACING, 0)

								if trash_button():
									ensure_push_state()
									del binds[i]
									continue

								i += 1

						imgui.dummy(LIGHT_SIZE)

						imgui.same_line(0, LIGHT_SPACING)

						if imgui.button("<new>", BIND_BUTTON_SIZE):
							ensure_push_state()
							binds.append(Bind())
							start_rebinding(len(binds) - 1)

					imgui.end_child()

			with disabled(state().selected == -1):
				with style_color(imgui.Col_.text, RED if running else GREEN):
					if imgui.button(icons_fontawesome_4.ICON_FA_STOP if running else icons_fontawesome_4.ICON_FA_PLAY, (imgui.get_content_region_avail().x, 0)):
						running = not running

						if running:
							for bind in profile().binds:
								remap_input(bind)
						else:
							keyboard.unhook_all()
							mouse.unhook_all()
							pressed_binds = []
							for event in bind_threads.values():
								event.set()
							bind_threads = {}

	if rebinding == -1 and not running:
		if imgui.get_io().key_ctrl and imgui.is_key_pressed(imgui.Key.z):
			change_state(-1)
			
		if imgui.get_io().key_ctrl and imgui.is_key_pressed(imgui.Key.y):
			change_state(1)



def load_settings():
	if data := hello_imgui.load_user_pref("state"):
		try:
			state_stack.append(pickle.loads(base64.b64decode(data)))
			return
		except Exception:
			assert False

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
	params.app_window_params.restore_previous_geometry = True
	params.imgui_window_params.enable_viewports = True	# For popups to be able to ignore window bounds
	params.callbacks.post_init = load_settings
	params.callbacks.load_additional_fonts = load_fonts
	params.callbacks.before_exit = save_settings
	params.callbacks.show_gui = gui

	immapp.run(params)
