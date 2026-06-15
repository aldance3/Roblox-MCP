# Roblox-MCP
Connects to the roblox built in MCP server and lets you use any ai model (paid, or free.) Whether in manual mode (ideal for web based AI's.) or automatic mode (Using an api key, this allows the ai direct access to tool calls.)


Automatic mode will automatically paste in the Insturctions.txt file, so you dont have to.

INSTRUCTIONS (Web based ai.):
  1: Go to any AI (Claude, Chatgpt, Deepseek, Gemini, any AI.)
  2: Paste in the contents of Instructions.txt
  3: Now ask it what you want in your game!
  4: Copy any Json code it gives you
  5: Use command run inside of the CLI
  6: Once notepad opens, Ctrl+A > backspace/delete > paste in the Json > Save it > Close notepad
  7: Thats all for manual mode.
INSTRUCTIONS (Automatic mode)
  1: Edit your preferred model from your preferred provider, and add your API key.
  2: Ask the AI what you want inside of the CLI.
  3: Thats all for automatic mode.

Commands:
  * Output - Outputs the output of the most recent tool calls.
  * Clear - Clears the output buffer
  * Run - Open notepad to paste/write a batch JSON, then execute it
  * History - Show last 10 output history entries (indexes 1-10)
  * Help [tool] - Tool list, or detailed help for a specific tool
  * Exit / Quit - Exits the client.
Available tools:
  character_navigation  {"datamodel_type": ...}
  execute_luau  {"code": ..., "datamodel_type": ...}
  generate_material  {"materialId": ..., "materialDescription": ..., "baseMaterial": ..., "materialPattern": ...}
  generate_mesh  {"textPrompt": ...}
  generate_procedural_model  {"prompt": ...}
  get_console_output
  get_studio_state
  http_get  {"url": ...}
  insert_from_creator_store  {"searchId": ...}
  inspect_instance  {"path": ...}
  list_roblox_studios
  multi_edit  {"datamodel_type": ..., "file_path": ..., "edits": ...}
  screen_capture  {"capture_id": ...}
  script_grep  {"query": ...}
  script_read  {"target_file": ...}
  script_search  {"keywords": ...}
  search_creator_store  {"query": ...}
  search_game_tree
  set_active_studio  {"studio_id": ...}
  skill  {"skill_name": ...}
  start_stop_play  {"is_start": ...}
  store_image  {"filePath": ...}
  subagent  {"description": ..., "subagent_type": ..., "task": ...}
  upload_image  {"imagePaths": ...}
  user_keyboard_input  {"actions": ..., "datamodel_type": ...}
  user_mouse_input  {"actions": ..., "datamodel_type": ...}
  wait_job_finished  {"generationId": ...}
