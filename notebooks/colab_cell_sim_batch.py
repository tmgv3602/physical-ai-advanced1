# ============================================================================
# Colab 用：day2_llm_pick_place.ipynb のセル9の後に「新しいセル」として貼って実行する
# REQ-FUN-002（実行を許可された計画で、物体が置き場に置かれる）の統計評価用
#
# - 物体の初期位置を ±2cm ランダムにずらす（毎回同じ物理を繰り返すだけの評価を避ける）
# - 4種類の指示 × 6回 = 24 エピソード、動画なし（T4 で十数分の想定）
# - ログは day2 と同じ episodes.jsonl に追記される（ハッシュチェーンは継続）
# ============================================================================
import random

JITTER = 0.02
random.seed(20261030)

def reset_world():                      # run_episode が呼ぶ reset_world を差し替える
    global _weld
    if _weld is not None:
        RIGID.delete_weld_constraint(*_weld); _weld = None
    for oid, o in world.OBJECTS.items():
        x, y, z = o['pos']
        cubes[oid].set_pos(np.array([x + random.uniform(-JITTER, JITTER),
                                     y + random.uniform(-JITTER, JITTER), z]))
        cubes[oid].set_quat(np.array([1.0, 0, 0, 0]))
    franka.set_dofs_position(HOME)
    franka.control_dofs_position(HOME[:7], ARM)
    franka.control_dofs_position(HOME[7:], FINGERS)
    wait(30)

batch = ['赤い箱を置き場Aに置いて', '青い箱を置き場Bに置いて',
         '赤い箱を置き場Bに置いて', '青い箱を置き場Aに置いて'] * 6
results = [run_episode(s, PLANNER_SAFE)['body']['outcome'] for s in batch]
print({k: results.count(k) for k in set(results)})
print('audit log verify:', audit_log.verify(f'{OUT}/logs/episodes.jsonl'))

# 終わったら Drive の pai_final/logs/episodes.jsonl をダウンロードし、
# リポジトリの results/sim/episodes.jsonl として commit → CI が自動で取り込む
