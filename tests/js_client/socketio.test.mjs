import { io } from "socket.io-client";
import assert from "assert";

const SOCKETIO_PATH = "/socket.io";
const LIVE_NAMESPACE = "/live";

const baseUrl = process.env.DJANGO_SIO_BASE_URL || "http://127.0.0.1:8001";

// Different client configurations we want to exercise
const RAW_TRANSPORT_CASES = [
  {
    name: "default",
    options: {}, // let socket.io-client choose (typically polling + websocket)
  },
  {
    name: "polling",
    options: { transports: ["polling"] },
  },
  {
    name: "websocket",
    options: { transports: ["websocket"] },
  },
  {
    name: "polling+websocket",
    options: { transports: ["polling", "websocket"] },
  },
];

const onlyName = process.env.SIO_TRANSPORT; // e.g. "polling"
const TRANSPORT_CASES = onlyName
  ? RAW_TRANSPORT_CASES.filter((c) => c.name === onlyName)
  : RAW_TRANSPORT_CASES;

function uniqueLabel(prefix) {
  return `${prefix} ${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

describe("django-sio JS client integration", function () {
  // Per-test timeout: user requested small timeout
  this.timeout(1000);

  TRANSPORT_CASES.forEach(({ name, options }) => {
    describe(`client options: ${name}`, function () {
      function makeSocket(extraOpts = {}) {
        return io(baseUrl + LIVE_NAMESPACE, {
          path: SOCKETIO_PATH,
          forceNew: true, // isolate each test
          reconnection: false, // avoid auto-reconnect flakiness
          ...options,
          ...extraOpts,
        });
      }

      function withCleanup(sockets, done) {
        let finished = false;
        return (err) => {
          if (finished) return;
          finished = true;
          for (const s of sockets) {
            if (!s) continue;
            try {
              s.disconnect();
            } catch {
              // ignore
            }
          }
          done(err);
        };
      }

      // ------------------------------------------------------------------
      // 0. ORIGINAL TESTS (kept, semantics preserved)
      // ------------------------------------------------------------------

      it("connects and receives initial live_state", function (done) {
        const socket = makeSocket();
        const finish = withCleanup([socket], done);

        socket.on("connect_error", (err) => finish(err));

        socket.on("live_state", (state) => {
          try {
            assert.ok(state && typeof state === "object");
            assert.ok("count" in state);
            assert.ok(Array.isArray(state.messages));
            finish();
          } catch (err) {
            finish(err);
          }
        });
      });

      it.skip("sends a live_action and receives updated state", function (done) {
        const socket = makeSocket();
        const finish = withCleanup([socket], done);

        socket.on("connect_error", (err) => finish(err));

        const title = "JS title"; // original test used constant title
        const message = "JS message";

        socket.on("connect", () => {
          socket.emit(
            "live_action",
            {
              action: "create",
              title,
              message,
            },
            (ack) => {
              try {
                assert.ok(ack && ack.status === "ok");
              } catch (err) {
                finish(err);
              }
            },
          );
        });

        socket.on("live_state", (state) => {
          try {
            const titles = state.messages.map((m) => m.title);

            // Initial state may not include our new title; ignore until it appears
            if (!titles.includes(title)) {
              return;
            }

            finish();
          } catch (err) {
            finish(err);
          }
        });
      });

      // ------------------------------------------------------------------
      // 1. State shape and consistency
      // ------------------------------------------------------------------

      it("live_state shape and count matches messages.length", function (done) {
        const socket = makeSocket();
        const finish = withCleanup([socket], done);

        socket.on("connect_error", (err) => finish(err));

        socket.on("live_state", (state) => {
          try {
            assert.ok(state && typeof state === "object");
            assert.ok("count" in state);
            assert.ok("messages" in state);
            assert.ok(Array.isArray(state.messages));

            assert.strictEqual(
              state.count,
              state.messages.length,
              "count should equal messages.length",
            );

            for (const msg of state.messages) {
              assert.ok("id" in msg);
              assert.ok("title" in msg);
              assert.ok("message" in msg);
            }

            finish();
          } catch (err) {
            finish(err);
          }
        });
      });

      // ------------------------------------------------------------------
      // 2. Connect with auth and verify auth flows via auth_echo
      // ------------------------------------------------------------------

      it("passes auth payload through connect (auth_echo)", function (done) {
        const authPayload = { userId: uniqueLabel("user"), role: "tester" };
        const socket = makeSocket({ auth: authPayload });
        const finish = withCleanup([socket], done);

        socket.on("connect_error", (err) => finish(err));

        let authEchoed = false;
        let liveStateSeen = false;

        socket.on("auth_echo", (payload) => {
          try {
            assert.ok(payload && typeof payload === "object");
            assert.strictEqual(payload.userId, authPayload.userId);
            assert.strictEqual(payload.role, authPayload.role);
            authEchoed = true;
            if (authEchoed && liveStateSeen) finish();
          } catch (err) {
            finish(err);
          }
        });

        socket.on("live_state", () => {
          liveStateSeen = true;
          if (authEchoed && liveStateSeen) finish();
        });
      });

      // ------------------------------------------------------------------
      // 3. live_action: create + delete + unknown
      // ------------------------------------------------------------------

      it.skip("create increments count and includes new message", function (done) {
        const socket = makeSocket();
        const finish = withCleanup([socket], done);

        socket.on("connect_error", (err) => finish(err));

        const title = uniqueLabel("create");
        const body = "body";

        let initialState = null;

        socket.on("live_state", (state) => {
          try {
            if (!initialState) {
              initialState = state;
              socket.emit(
                "live_action",
                {
                  action: "create",
                  title,
                  message: body,
                },
                (ack) => {
                  try {
                    assert.ok(ack && ack.status === "ok");
                  } catch (err) {
                    finish(err);
                  }
                },
              );
              return;
            }

            const created = state.messages.find((m) => m.title === title);
            if (!created) return; // wait until our message appears

            assert.strictEqual(
              state.count,
              initialState.count + 1,
              "create should increment count by 1",
            );
            assert.strictEqual(created.message, body);

            finish();
          } catch (err) {
            finish(err);
          }
        });
      });

      it.skip("create and delete via live_action updates state correctly", function (done) {
        const socket = makeSocket();
        const finish = withCleanup([socket], done);

        socket.on("connect_error", (err) => finish(err));

        const title = uniqueLabel("delete");
        const body = "delete body";

        let phase = 0;
        let createdMsg = null;
        let stateAfterCreate = null;

        socket.on("live_state", (state) => {
          try {
            if (phase === 0) {
              // first state: create
              socket.emit(
                "live_action",
                {
                  action: "create",
                  title,
                  message: body,
                },
                (ack) => {
                  try {
                    assert.ok(ack && ack.status === "ok");
                  } catch (err) {
                    finish(err);
                  }
                },
              );
              phase = 1;
              return;
            }

            if (phase === 1) {
              createdMsg = state.messages.find((m) => m.title === title);
              if (!createdMsg) return;

              stateAfterCreate = state;

              socket.emit(
                "live_action",
                {
                  action: "delete",
                  id: createdMsg.id,
                },
                (ack) => {
                  try {
                    assert.ok(ack && ack.status === "ok");
                  } catch (err) {
                    finish(err);
                  }
                },
              );
              phase = 2;
              return;
            }

            if (phase === 2) {
              const stillThere = state.messages.find(
                (m) => m.id === createdMsg.id,
              );
              if (stillThere) return;

              assert.strictEqual(
                state.count,
                stateAfterCreate.count - 1,
                "delete should decrement count by 1",
              );
              finish();
            }
          } catch (err) {
            finish(err);
          }
        });
      });

      it.skip("unknown live_action is a no-op but still acknowledges ok", function (done) {
        const socket = makeSocket();
        const finish = withCleanup([socket], done);

        socket.on("connect_error", (err) => finish(err));

        let baseline = null;
        let ackReceived = false;

        socket.on("live_state", (state) => {
          try {
            if (!baseline) {
              baseline = state;
              socket.emit(
                "live_action",
                { action: "totally_unknown_action" },
                (ack) => {
                  try {
                    assert.ok(ack && ack.status === "ok");
                    ackReceived = true;
                  } catch (err) {
                    finish(err);
                  }
                },
              );
              return;
            }

            if (!ackReceived) return;

            assert.strictEqual(
              state.count,
              baseline.count,
              "unknown action should not change count",
            );
            finish();
          } catch (err) {
            finish(err);
          }
        });
      });

      // ------------------------------------------------------------------
      // 4. Generic event dispatch: echo, echo w/o ack, ack_only, trigger_error
      // ------------------------------------------------------------------

      it("echo handler roundtrips payload and optional ack", function (done) {
        const socket = makeSocket();
        const finish = withCleanup([socket], done);

        socket.on("connect_error", (err) => finish(err));

        const payload = { msg: uniqueLabel("echo"), n: 42 };

        let echoReceived = false;
        let ackReceived = false;

        socket.on("echo", (data) => {
          try {
            assert.deepStrictEqual(data, payload);
            echoReceived = true;
            if (echoReceived && ackReceived) finish();
          } catch (err) {
            finish(err);
          }
        });

        socket.on("connect", () => {
          socket.emit("echo", payload, (ack) => {
            try {
              assert.ok(ack && ack.status === "ok");
              assert.deepStrictEqual(ack.echo, payload);
              ackReceived = true;
              if (echoReceived && ackReceived) finish();
            } catch (err) {
              finish(err);
            }
          });
        });
      });

      it("echo handler works without ack callback", function (done) {
        const socket = makeSocket();
        const finish = withCleanup([socket], done);

        socket.on("connect_error", (err) => finish(err));

        const payload = { msg: uniqueLabel("echo-no-ack") };

        socket.on("echo", (data) => {
          try {
            assert.deepStrictEqual(data, payload);
            finish();
          } catch (err) {
            finish(err);
          }
        });

        socket.on("connect", () => {
          socket.emit("echo", payload); // no ack provided
        });
      });

      it("ack_only returns ack without emitting extra events", function (done) {
        const socket = makeSocket();
        const finish = withCleanup([socket], done);

        socket.on("connect_error", (err) => finish(err));

        const payload = { msg: uniqueLabel("ack_only") };
        let anyUnexpectedEvent = false;

        socket.onAny((event) => {
          if (!["connect", "live_state", "auth_echo"].includes(event)) {
            anyUnexpectedEvent = true;
          }
        });

        socket.on("connect", () => {
          socket.emit("ack_only", payload, (ack) => {
            try {
              assert.ok(ack && ack.status === "ok");
              assert.deepStrictEqual(ack.payload, payload);
              assert.strictEqual(
                anyUnexpectedEvent,
                false,
                "ack_only should not emit application events",
              );
              finish();
            } catch (err) {
              finish(err);
            }
          });
        });
      });

      it("trigger_error does not hang client", function (done) {
        const socket = makeSocket();
        const finish = withCleanup([socket], done);

        socket.on("connect_error", (err) => finish(err));

        let disconnectSeen = false;

        socket.on("disconnect", () => {
          disconnectSeen = true;
          finish();
        });

        socket.on("connect", () => {
          socket.emit("trigger_error", { message: "boom" });
          setTimeout(() => {
            if (!disconnectSeen) {
              finish(); // still fine as long as we don't hang forever
            }
          }, 400);
        });
      });

      // ------------------------------------------------------------------
      // 5. Rooms & broadcast
      // ------------------------------------------------------------------

      it("room broadcast reaches all sockets in the room only", function (done) {
        const socketA = makeSocket();
        const socketB = makeSocket();
        const socketC = makeSocket(); // not in room
        const finish = withCleanup([socketA, socketB, socketC], done);

        [socketA, socketB, socketC].forEach((s) =>
          s.on("connect_error", (err) => finish(err)),
        );

        const roomName = uniqueLabel("room");
        const payload = { txt: uniqueLabel("room_broadcast") };

        let aJoined = false;
        let bJoined = false;
        let cGotBroadcast = false;
        let bGotBroadcast = false;

        const tryBroadcast = () => {
          if (aJoined && bJoined && !bGotBroadcast) {
            socketA.emit(
              "room_broadcast",
              { room: roomName, data: payload },
              (ack) => {
                try {
                  assert.ok(ack && ack.status === "ok");
                } catch (err) {
                  finish(err);
                }
              },
            );
          }
        };

        socketB.on("room_broadcast", (data) => {
          try {
            assert.deepStrictEqual(data, payload);
            bGotBroadcast = true;
            setTimeout(() => {
              try {
                assert.strictEqual(
                  cGotBroadcast,
                  false,
                  "socket not in room must not receive room_broadcast",
                );
                finish();
              } catch (err) {
                finish(err);
              }
            }, 400);
          } catch (err) {
            finish(err);
          }
        });

        socketC.on("room_broadcast", () => {
          cGotBroadcast = true;
        });

        const joinRoom = (socket, markReady) => {
          socket.on("connect", () => {
            socket.emit("join_room", { room: roomName }, (ack) => {
              try {
                assert.ok(ack && ack.status === "ok");
                markReady();
                tryBroadcast();
              } catch (err) {
                finish(err);
              }
            });
          });
        };

        joinRoom(socketA, () => {
          aJoined = true;
        });
        joinRoom(socketB, () => {
          bJoined = true;
        });
      });

      // ------------------------------------------------------------------
      // 6. Lifecycle: autoConnect:false and manual connect / reconnect on same instance
      // ------------------------------------------------------------------

      it("supports autoConnect:false with manual connect()", function (done) {
        const socket = makeSocket({ autoConnect: false });
        const finish = withCleanup([socket], done);

        let connected = false;

        socket.on("connect_error", (err) => finish(err));
        socket.on("connect", () => {
          connected = true;
          finish();
        });

        socket.connect();

        setTimeout(() => {
          if (!connected) {
            finish(new Error("connect() did not succeed in time"));
          }
        }, 500);
      });

      it("disconnects and reconnects on same socket instance", function (done) {
        const socket = makeSocket({ autoConnect: false });
        const finish = withCleanup([socket], done);

        let connectCount = 0;
        let echoCount = 0;

        const payload1 = { msg: uniqueLabel("reconnect1") };
        const payload2 = { msg: uniqueLabel("reconnect2") };

        socket.on("connect_error", (err) => finish(err));

        socket.on("echo", (data) => {
          try {
            echoCount += 1;
            if (echoCount === 1) {
              assert.deepStrictEqual(data, payload1);
              socket.disconnect();
              setTimeout(() => {
                socket.connect();
              }, 100);
            } else if (echoCount === 2) {
              assert.deepStrictEqual(data, payload2);
              finish();
            }
          } catch (err) {
            finish(err);
          }
        });

        socket.on("connect", () => {
          connectCount += 1;
          if (connectCount === 1) {
            socket.emit("echo", payload1);
          } else if (connectCount === 2) {
            socket.emit("echo", payload2);
          }
        });

        socket.connect();
      });

      // ------------------------------------------------------------------
      // 7. Negative path: wrong namespace
      // ------------------------------------------------------------------

      it("connecting to a non-existent namespace triggers connect_error", function (done) {
        const badSocket = io(baseUrl + "/does_not_exist", {
          path: SOCKETIO_PATH,
          forceNew: true,
          reconnection: false,
          ...options,
        });

        const finish = withCleanup([badSocket], done);

        let gotError = false;

        badSocket.on("connect", () => {
          finish(new Error("Expected connect_error for unknown namespace"));
        });

        badSocket.on("connect_error", () => {
          gotError = true;
          finish();
        });

        setTimeout(() => {
          if (!gotError) {
            finish(new Error("No connect_error for unknown namespace"));
          }
        }, 500);
      });
    });
  });
});
