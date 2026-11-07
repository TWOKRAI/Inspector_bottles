from multiprocess_framework.modules.process_manager_module.tests.test_supervision_status_system_stop import _Light
lt = _Light()
calls = []
lt.pm._state_store_manager.handle_state_set = lambda msg: (calls.append(msg["data"]["path"]) or {"status": "rejected", "reason": "middleware"})
lt.pm._cmd_system_shutdown({"_sender": "gui"})
print("calls:", len(calls))
lt.pm._publish_system_stop()
print("calls after second publish (retry expected if write failed):", len(calls))
print("warnings logged:", lt.pm._log_warning.call_count, "errors logged:", lt.pm._log_error.call_count)
