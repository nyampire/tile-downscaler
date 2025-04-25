#!/usr/bin/env python3
"""
downscale_tiles.py - XYZタイル形式の地図タイルを高ズームレベルから低ズームレベルへダウンスケールするスクリプト
"""

import os
import sys
import argparse
import logging
from concurrent.futures import ProcessPoolExecutor
from PIL import Image

def setup_logging(verbose=False):
    """ロギング設定をセットアップする"""
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

def create_tile(source_tiles, target_x, target_y, target_dir, tile_size=256):
    """
    4つのソースタイルから1つの低ズームレベルタイルを生成する

    Args:
        source_tiles: ソースタイルのリスト [(x, y, path), ...]
        target_x: 生成するタイルのX座標
        target_y: 生成するタイルのY座標
        target_dir: 生成したタイルを保存するディレクトリ
        tile_size: タイルのサイズ（ピクセル単位）
    """
    # ターゲットのX座標のディレクトリを作成
    target_x_dir = os.path.join(target_dir, str(target_x))
    os.makedirs(target_x_dir, exist_ok=True)

    # 4つの象限のデータを準備 (0:左上, 1:右上, 2:左下, 3:右下)
    quadrants = [None, None, None, None]

    # タイルの情報をログに記録
    logging.debug(f"タイル {target_x}/{target_y} の生成: ソースタイル数 {len(source_tiles)}")

    # 各ソースタイルを適切な象限に割り当て
    for x, y, path in source_tiles:
        quadrant_x = x % 2  # 0: 左, 1: 右
        quadrant_y = y % 2  # 0: 上, 1: 下
        quadrant = quadrant_x + (quadrant_y * 2)

        try:
            img = Image.open(path)
            # 画像モードがRGBAでない場合はRGBAに変換
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            quadrants[quadrant] = img
            logging.debug(f"  読み込み: {x}/{y} → 象限 {quadrant}")
        except Exception as e:
            logging.warning(f"  警告: 画像読み込み失敗 {path}: {e}")

    # 欠けているタイルを透明色で補完
    missing = [i for i, q in enumerate(quadrants) if q is None]
    if missing:
        # 欠けているタイルを透明色で補完するが、警告ログは出力しない
        for idx in missing:
            # 透明なタイルを作成
            quadrants[idx] = Image.new('RGBA', (tile_size, tile_size), (0, 0, 0, 0))

    # タイルのサイズを確認し、必要に応じてリサイズ
    for i, q in enumerate(quadrants):
        if q.width != tile_size or q.height != tile_size:
            logging.warning(f"  警告: 象限 {i} のタイルサイズが標準と異なります ({q.width}x{q.height})、リサイズします")
            quadrants[i] = q.resize((tile_size, tile_size), Image.LANCZOS)

    # 4つのタイルを結合
    merged = Image.new('RGBA', (tile_size*2, tile_size*2), (0, 0, 0, 0))
    merged.paste(quadrants[0], (0, 0))                # 左上
    merged.paste(quadrants[1], (tile_size, 0))        # 右上
    merged.paste(quadrants[2], (0, tile_size))        # 左下
    merged.paste(quadrants[3], (tile_size, tile_size))  # 右下

    # リサイズして保存
    merged = merged.resize((tile_size, tile_size), Image.LANCZOS)

    # 拡張子を特定
    ext = '.png'  # 透明色を使用するためPNGがデフォルト

    output_path = os.path.join(target_x_dir, f"{target_y}{ext}")
    merged.save(output_path)
    logging.debug(f"  保存完了: {output_path}")

    return output_path

def create_lower_zoom_tiles(source_zoom, dest_zoom_min, tiles_dir, workers=1):
    """
    XYZ形式のタイルからより低いズームレベルのタイルを生成する
    欠けているタイルは透明色で補完

    Args:
        source_zoom: ソースタイルのズームレベル
        dest_zoom_min: 生成する最小ズームレベル
        tiles_dir: タイルディレクトリのルートパス
        workers: 並列処理に使用するワーカー数
    """
    logging.info(f"ソースディレクトリ: {tiles_dir}/{source_zoom}")

    for current_zoom in range(source_zoom - 1, dest_zoom_min - 1, -1):
        logging.info(f"\nズームレベル {current_zoom} のタイルを生成中...")

        # ソースとターゲットのディレクトリを設定
        source_dir = os.path.join(tiles_dir, str(current_zoom + 1))
        target_dir = os.path.join(tiles_dir, str(current_zoom))
        os.makedirs(target_dir, exist_ok=True)

        # ソースディレクトリから全タイルのリストを取得
        tiles = []
        try:
            for x_dir in os.listdir(source_dir):
                x_dir_path = os.path.join(source_dir, x_dir)
                if not os.path.isdir(x_dir_path):
                    continue

                try:
                    x = int(x_dir)
                    for y_file in os.listdir(x_dir_path):
                        if not (y_file.endswith('.jpg') or y_file.endswith('.png')):
                            continue

                        try:
                            y = int(os.path.splitext(y_file)[0])
                            tile_path = os.path.join(x_dir_path, y_file)
                            tiles.append((x, y, tile_path))
                        except ValueError:
                            logging.warning(f"不正なファイル名: {y_file}")
                except ValueError:
                    logging.warning(f"不正なディレクトリ名: {x_dir}")
        except FileNotFoundError:
            logging.error(f"ソースディレクトリが見つかりません: {source_dir}")
            sys.exit(1)

        logging.info(f"ソースの総タイル数: {len(tiles)}")
        if not tiles:
            logging.error(f"ズームレベル {current_zoom + 1} にタイルが見つかりません")
            sys.exit(1)

        # 対象ズームレベルのタイルを計算
        target_tiles = {}
        for x, y, path in tiles:
            target_x = x // 2
            target_y = y // 2

            if (target_x, target_y) not in target_tiles:
                target_tiles[(target_x, target_y)] = []

            target_tiles[(target_x, target_y)].append((x, y, path))

        logging.info(f"生成されるタイル数: {len(target_tiles)}")

        # 並列処理または逐次処理を選択
        if workers > 1:
            logging.info(f"{workers}個のワーカーで並列処理を開始します")
            with ProcessPoolExecutor(max_workers=workers) as executor:
                futures = []
                for (target_x, target_y), source_tiles in target_tiles.items():
                    futures.append(
                        executor.submit(create_tile, source_tiles, target_x, target_y, target_dir)
                    )

                # 結果を取得
                for future in futures:
                    try:
                        future.result()
                    except Exception as e:
                        logging.error(f"タイル生成エラー: {e}")
        else:
            # 各ターゲットタイルを生成
            for (target_x, target_y), source_tiles in target_tiles.items():
                try:
                    create_tile(source_tiles, target_x, target_y, target_dir)
                except Exception as e:
                    logging.error(f"タイル {target_x}/{target_y} の生成エラー: {e}")

        logging.info(f"ズームレベル {current_zoom} の生成完了")

def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(description='XYZ形式のタイルからより低いズームレベルのタイルを生成します')
    parser.add_argument('tiles_dir', help='タイルディレクトリのルートパス')
    parser.add_argument('--source-zoom', '-s', type=int, default=18, help='ソースタイルのズームレベル (デフォルト: 18)')
    parser.add_argument('--dest-zoom-min', '-d', type=int, default=10, help='生成する最小ズームレベル (デフォルト: 10)')
    parser.add_argument('--workers', '-w', type=int, default=1, help='並列処理に使用するワーカー数 (デフォルト: 1)')
    parser.add_argument('--verbose', '-v', action='store_true', help='詳細なログ出力を有効にする')

    args = parser.parse_args()

    setup_logging(args.verbose)

    logging.info(f"タイル変換を開始: ズームレベル {args.source_zoom} → {args.dest_zoom_min}")

    create_lower_zoom_tiles(
        args.source_zoom,
        args.dest_zoom_min,
        args.tiles_dir,
        args.workers
    )

    logging.info("すべてのタイル生成が完了しました")

if __name__ == "__main__":
    main()
