# debug failed

## redo nomem baselin

```bash
cd ~/projects/mem-comp-26/harness

# 1) backup current candidate config
cp candidates.json "candidates.backup.$(date +%Y%m%d_%H%M%S).json"

# 2) set a fresh no-memory candidate (single run => 9 instances)
cat > candidates.json <<'JSON'
[
  {
    "run_name": "kimsia_glm47_nomem_v1",
    "agent_docker_image": "kimsia-mem-agent:latest",
    "llm_quota_total": 200,
    "llm_quota_instance": 2,
    "enable_memory": false,
    "timeout_s": 7200,
    "env": {
      "MODEL_NAME": "litellm_proxy/glm-4.7"
    }
  }
]
JSON

# 3) archive old results + clean
ts="$(date +%Y%m%d_%H%M%S)"
sudo chown -R "$USER:$(id -gn)" results workdir 2>/dev/null || true
mkdir -p "run_archive_${ts}"
[ -d results ] && mv results "run_archive_${ts}/results"
mkdir -p results
rm -rf workdir/*
sudo docker ps -aq --filter "name=^/memcomp-" | xargs -r sudo docker rm -f

# 4) run
sudo -E "$(pwd)/.venv/bin/python" main.py | tee "run_${ts}_kimsia_glm47_nomem_v1.log"
```

quick verify after run

```bash
python3 - <<'PY'
from pathlib import Path
import json
run='kimsia_glm47_nomem_v1'
vals=sorted((Path('results')/run).glob('p*/_harness/verdict_val.json'))
ok=sum(1 for f in vals if json.load(open(f)).get('resolved'))
print(f'{run}: {ok}/{len(vals)}')
PY
```

## analyze failed instances

```bash
cd ~/projects/mem-comp-26/harness
run="kimsia_glm47_nomem_v1"

echo "=== quick summary ($run) ==="
python3 - <<'PY'
from pathlib import Path
import json
run="kimsia_glm47_nomem_v1"
base=Path("results")/run
rows=[]
for d in sorted(base.glob("p*i*")):
    try:
        v=json.load(open(d/"_harness"/"verdict_val.json"))
        i=json.load(open(d/"instance.json"))
        g=json.load(open(d/"_harness"/"verdict_gen.json"))
        rows.append((d.name, i.get("repo_language","?"), i.get("repo","?"), g.get("instance_id","?"), bool(v.get("resolved"))))
    except Exception:
        rows.append((d.name,"?","?","?","MISSING_FILES"))
for r in rows:
    print(f"{r[0]} | lang={r[1]} | resolved={r[4]} | repo={r[2]} | instance_id={r[3]}")
ok=sum(1 for r in rows if r[4] is True)
print(f"\nresolved: {ok}/{len(rows)}")
PY
```

## results

```bash
=== quick summary (kimsia_glm47_nomem_v1) ===
p00i00 | lang=js | resolved=True | repo=NodeBB/NodeBB | instance_id=instance_NodeBB__NodeBB-397835a05a8e2897324e566b41c5e616e172b4af-v89631a1cdb318276acb48860c5d78077211397c6
p00i01 | lang=js | resolved=True | repo=NodeBB/NodeBB | instance_id=instance_NodeBB__NodeBB-04998908ba6721d64eba79ae3b65a351dcfbc5b5-vnan
p00i02 | lang=js | resolved=True | repo=NodeBB/NodeBB | instance_id=instance_NodeBB__NodeBB-f9ce92df988db7c1ae55d9ef96d247d27478bc70-vf2cf3cbd463b7ad942381f1c6d077626485a1e9e
p01i00 | lang=python | resolved=True | repo=qutebrowser/qutebrowser | instance_id=instance_qutebrowser__qutebrowser-96b997802e942937e81d2b8a32d08f00d3f4bc4e-v5fc38aaf22415ab0b70567368332beee7955b367
p01i01 | lang=python | resolved=True | repo=qutebrowser/qutebrowser | instance_id=instance_qutebrowser__qutebrowser-c580ebf0801e5a3ecabc54f327498bb753c6d5f2-v2ef375ac784985212b1805e1d0431dc8f1b3c171
p01i02 | lang=python | resolved=True | repo=qutebrowser/qutebrowser | instance_id=instance_qutebrowser__qutebrowser-f91ace96223cac8161c16dd061907e138fe85111-v059c6fdc75567943479b23ebca7c07b5e9a7f34c
p02i00 | lang=js | resolved=True | repo=element-hq/element-web | instance_id=instance_element-hq__element-web-f0359a5c180b8fec4329c77adcf967c8d3b7b787-vnan
p02i01 | lang=js | resolved=False | repo=element-hq/element-web | instance_id=instance_element-hq__element-web-71fe08ea0f159ccb707904d87f0a4aef205a167c-vnan
p02i02 | lang=js | resolved=False | repo=element-hq/element-web | instance_id=instance_element-hq__element-web-1077729a19c0ce902e713cf6fab42c91fb7907f1-vnan

resolved: 7/9
```

## extract failed

```bash
cd ~/projects/mem-comp-26/harness
run="kimsia_glm47_nomem_v1"
for p in p02i01 p02i02; do
  inst="results/$run/$p"
  echo "================ $p ================"
  jq '.resolved,.status,("all="+(.all_tests|length|tostring)),("passed="+(.passed_tests|length|tostring))' "$inst/_harness/verdict_val.json"

  echo "-- failed tests --"
  python3 - <<PY
import json
v=json.load(open("$inst/_harness/verdict_val.json"))
all_tests=v.get("all_tests",[]) or []
passed=set(v.get("passed_tests",[]) or [])
failed=[t for t in all_tests if t not in passed]
print("\\n".join(failed[:30]))
print("failed_count =", len(failed))
PY

  echo "-- files changed in patch --"
  rg '^diff --git ' "$inst/patch.diff" || true

  echo "-- agent errors / warnings --"
  rg -n "Traceback|Exception|error|timeout|BadRequestError|done! status" "$inst/_harness/agent.log" | tail -n 40 || true

  echo "-- validation tail --"
  tail -n 100 "$inst/_harness/validation.log" || true
done
```

## failed

```bash
================ p02i01 ================
false
{
  "StatusCode": 0
}
"all=198"
"passed=284"
-- failed tests --

essage with invited email
test/components/views/rooms/RoomPreviewBar-test.tsx | when invitedEmail is not associated with current account | renders join button
test/components/views/rooms/RoomPreviewBar-test.tsx | <RoomPreviewBar /> | renders viewing room message when room an be previewed
test/components/views/rooms/RoomPreviewBar-test.tsx | <RoomPreviewBar /> | renders not logged in message
test/components/views/rooms/RoomPreviewBar-test.tsx | when client fails to get 3PIDs | renders join button
test/components/views/rooms/RoomPreviewBar-test.tsx | <RoomPreviewBar /> | renders rejecting message
test/components/views/right_panel/UserInfo-test.tsx | with crypto enabled | renders <BasicUserInfo />
test/components/views/rooms/RoomPreviewBar-test.tsx | <RoomPreviewBar /> | renders loading message
test/components/views/rooms/RoomPreviewBar-test.tsx | for a non-dm room | renders join and reject action buttons correctly
test/components/views/rooms/RoomPreviewBar-test.tsx | <RoomPreviewBar /> | renders banned message
test/components/views/rooms/RoomPreviewBar-test.tsx | <RoomPreviewBar /> | renders kicked message
test/components/views/rooms/RoomPreviewBar-test.tsx | with an error | renders room not found error
test/components/views/rooms/RoomPreviewBar-test.tsx | when client has no identity server connected | renders join button
test/components/views/rooms/RoomPreviewBar-test.tsx | when client has no identity server connected | renders invite message with invited email
test/components/views/rooms/RoomPreviewBar-test.tsx | with an error | renders other errors
test/components/views/rooms/RoomPreviewBar-test.tsx | for a non-dm room | renders invite message
test/components/views/rooms/RoomPreviewBar-test.tsx | when client has an identity server connected | renders email mismatch message when invite email mxid doesnt match
test/components/views/rooms/RoomPreviewBar-test.tsx | <RoomPreviewBar /> | renders viewing room message when room can not be previewed
test/components/views/rooms/RoomPreviewBar-test.tsx | <RoomPreviewBar /> | renders joining message
test/components/views/rooms/RoomPreviewBar-test.tsx | for a dm room | renders invite message
test/components/views/rooms/RoomPreviewBar-test.tsx | when client has an identity server connected | renders invite message when invite email mxid match
test/components/views/rooms/RoomPreviewBar-test.tsx | for a non-dm room | rejects invite on secondary button click
test/components/views/rooms/RoomPreviewBar-test.tsx | for a non-dm room | renders reject and ignore action buttons when handler is provided
failed_count = 28
-- files changed in patch --
1:diff --git a/src/SlashCommands.tsx b/src/SlashCommands.tsx
23:diff --git a/src/components/views/avatars/BaseAvatar.tsx b/src/components/views/avatars/BaseAvatar.tsx
81:diff --git a/src/components/views/avatars/MemberAvatar.tsx b/src/components/views/avatars/MemberAvatar.tsx
102:diff --git a/src/components/views/elements/AppPermission.tsx b/src/components/views/elements/AppPermission.tsx
115:diff --git a/src/components/views/elements/EventListSummary.tsx b/src/components/views/elements/EventListSummary.tsx
130:diff --git a/src/components/views/messages/EncryptionEvent.tsx b/src/components/views/messages/EncryptionEvent.tsx
152:diff --git a/src/settings/Settings.tsx b/src/settings/Settings.tsx
-- agent errors / warnings --
122:2026-03-22T10:10:23.101001579Z done! status: Submitted
-- validation tail --
      "status": "PASSED"
    },
    {
      "name": "test/components/views/rooms/wysiwyg_composer/components/WysiwygComposer-test.tsx | Mentions and commands | selecting a command inserts the command",
      "status": "PASSED"
    },
    {
      "name": "test/components/views/rooms/wysiwyg_composer/components/WysiwygComposer-test.tsx | Mentions and commands | selecting an at-room completion inserts @room",
      "status": "PASSED"
      "status": "PASSED"
    },
    {
      "name": "test/components/views/rooms/wysiwyg_composer/components/WysiwygComposer-test.tsx | When settings require Ctrl+Enter to send | Should send a message when Ctrl+Enter is pressed",
      "status": "PASSED"
    },
    {
      "name": "test/components/views/rooms/wysiwyg_composer/components/WysiwygComposer-test.tsx | In message creation | Should not moving when the composer is filled",
      "status": "PASSED"
    },
    {
      "name": "test/components/views/rooms/wysiwyg_composer/components/WysiwygComposer-test.tsx | In message creation | Should moving when the composer is empty",
      "status": "PASSED"
    },
    {
      "name": "test/components/views/rooms/wysiwyg_composer/components/WysiwygComposer-test.tsx | Moving up | Should not moving when caret is not at beginning of the text",
      "status": "PASSED"
    },
    {
      "name": "test/components/views/rooms/wysiwyg_composer/components/WysiwygComposer-test.tsx | Moving up | Should not moving when the content has changed",
      "status": "PASSED"
    },
    {
      "name": "test/components/views/rooms/wysiwyg_composer/components/WysiwygComposer-test.tsx | Moving up | Should moving up",
      "status": "PASSED"

    },
    {
      "name": "test/voice-broadcast/components/atoms/VoiceBroadcastHeader-test.tsx | when rendering a live (grey) broadcast header with broadcast info | should render the header with a grey live badge",
      "status": "PASSED"
    },
    {
      "name": "test/voice-broadcast/components/atoms/VoiceBroadcastHeader-test.tsx | when rendering a non-live broadcast header | should render the header without a live badge",
      "status": "PASSED"
    },
    {
      "name": "test/components/views/emojipicker/EmojiPicker-test.tsx | EmojiPicker | should not mangle default order after filtering",
      "status": "PASSED"
    },
    {
      "name": "test/components/views/emojipicker/EmojiPicker-test.tsx | EmojiPicker | sort emojis by shortcode and size",
      "status": "PASSED"
    },
    {
      "name": "test/components/views/emojipicker/EmojiPicker-test.tsx | EmojiPicker | should allow keyboard navigation using arrow keys",
      "status": "PASSED"
    },
    {
      "name": "test/useTopic-test.tsx | useTopic | should display the room topic",
      "status": "PASSED"
    }
  ]
}================ p02i02 ================
false
{
  "StatusCode": 0
}
"all=386"
"passed=385"
-- failed tests --
test/unit-tests/components/viewmodels/roomlist/RoomListViewModel-test.tsx | Sticky room and active index | active index is calculated with the last opened room in a space
failed_count = 1
-- files changed in patch --
1:diff --git a/src/components/viewmodels/roomlist/useStickyRoomList.tsx b/src/components/viewmodels/roomlist/useStickyRoomList.tsx
90:diff --git a/src/stores/spaces/SpaceStore.ts b/src/stores/spaces/SpaceStore.ts
-- agent errors / warnings --
113:2026-03-22T10:19:58.907282763Z done! status: Submitted
-- validation tail --
      "status": "PASSED"
    },
    {
      "name": "test/unit-tests/utils/permalinks/MatrixToPermalinkConstructor-test.ts | parsePermalink | should raise an error for something that is not an URL",
      "status": "PASSED"
    },
    {
      "name": "test/unit-tests/utils/permalinks/MatrixToPermalinkConstructor-test.ts | parsePermalink | should raise an error for should raise an error for a non-matrix.to URL",
      "status": "PASSED"
    },
    {
      "name": "test/unit-tests/utils/permalinks/MatrixToPermalinkConstructor-test.ts | parsePermalink | should parse an MXID",
      "status": "PASSED"
    },
    {
      "name": "test/unit-tests/utils/permalinks/MatrixToPermalinkConstructor-test.ts | parsePermalink | should parse an MXID",
      "status": "PASSED"
    },
    {
      "name": "test/unit-tests/utils/permalinks/MatrixToPermalinkConstructor-test.ts | parsePermalink | should parse an MXID without protocol",
      "status": "PASSED"
    },
    {
      "name": "test/unit-tests/utils/permalinks/MatrixToPermalinkConstructor-test.ts | forRoom | constructs a link given a room ID and via servers",
      "status": "PASSED"
    },
    {
      "name": "test/unit-tests/utils/permalinks/MatrixToPermalinkConstructor-test.ts | forEvent | constructs a link given an event ID, room ID and via servers",
      "status": "PASSED"
    },
    {
      "name": "test/unit-tests/components/views/messages/MStickerBody-test.tsx | <MStickerBody/> | should show a tooltip on hover",
      "status": "PASSED"
    },
    {
      "name": "test/unit-tests/components/views/elements/SettingsField-test.tsx | <SettingsField /> | should render with the default label",
      "status": "PASSED"
    },
    {
      "name": "test/unit-tests/components/views/elements/SettingsField-test.tsx | <SettingsField /> | should call onChange when saving a change",
      "status": "PASSED"
    }
  ]
}
```
