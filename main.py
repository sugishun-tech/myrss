import json
import os
import sys
from datetime import datetime

import feedparser
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import (QApplication, QCalendarWidget, QHBoxLayout,
                             QLabel, QListWidget, QListWidgetItem, QMainWindow,
                             QPushButton, QStyle, QStyledItemDelegate,
                             QTextBrowser, QVBoxLayout, QWidget)

# --- 1. カレンダーのカスタマイズ (記事がある日にTを表示) ---


class MarkCalendar(QCalendarWidget):
    def paintCell(self, painter, rect, date):
        super().paintCell(painter, rect, date)
        year, month, day = str(date.year()), str(date.month()).zfill(2), str(date.day()).zfill(2)
        date_path = f"data/{year}/{month}/{day}"

        if os.path.exists(date_path) and any(f.endswith('.json') for f in os.listdir(date_path)):
            painter.save()
            painter.setPen(QColor("#ff4757"))
            font = painter.font()
            font.setPointSize(9)
            font.setBold(False)
            painter.setFont(font)
            target_rect = rect.adjusted(0, 1, -4, 0)
            painter.drawText(target_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, "T")
            painter.restore()

# --- 2. リストの見た目カスタマイズ (青いバーを消して矢印を出す) ---


class ArrowDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        painter.save()

        is_selected = option.state & QStyle.StateFlag.State_Selected

        # 背景描画
        painter.fillRect(option.rect, QColor("white"))

        text_margin = 10

        # 選択状態なら矢印を描画
        if is_selected:
            painter.setPen(QColor("#3498db"))
            arrow_font = QFont()
            arrow_font.setBold(False)
            painter.setFont(arrow_font)
            painter.drawText(option.rect.adjusted(5, 0, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "▶")
            text_margin = 25

        # テキストの描画
        painter.setPen(QColor("#2c3e50"))
        font = option.font
        if is_selected:
            font.setBold(False)
        painter.setFont(font)

        text_rect = option.rect.adjusted(text_margin, 0, -5, 0)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, index.data(Qt.ItemDataRole.DisplayRole))

        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(35)
        return size

# --- 3. RSS取得スレッド (favicon取得を廃止) ---


class FetchWorker(QThread):
    finished = pyqtSignal()
    progress = pyqtSignal(str)

    def run(self):
        if not os.path.exists('feeds.txt'):
            self.finished.emit()
            return
        with open('feeds.txt', 'r', encoding='utf-8') as f:
            urls = [line.strip() for line in f if line.strip()]

        for url in urls:
            try:
                domain = url.split('//')[-1].split('/')[0]
                self.progress.emit(f"取得中: {domain}")
                feed = feedparser.parse(url)

                for entry in feed.entries:
                    dt = datetime(*entry.published_parsed[:6]) if 'published_parsed' in entry else datetime.now()
                    dir_path = f"data/{dt.year}/{str(dt.month).zfill(2)}/{str(dt.day).zfill(2)}"
                    os.makedirs(dir_path, exist_ok=True)
                    file_path = os.path.join(dir_path, f"{hash(entry.link)}.json")
                    if not os.path.exists(file_path):
                        with open(file_path, 'w', encoding='utf-8') as f:
                            json.dump({
                                'title': entry.title,
                                'link': entry.link,
                                'summary': entry.get('summary', ''),
                                'domain': domain,
                                'date': dt.strftime('%Y-%m-%d %H:%M')
                            }, f, ensure_ascii=False)
            except:
                continue
        self.finished.emit()

# --- 4. メインウィンドウ ---


class MyRSS(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MyRSS Reader")
        self.resize(1000, 750)
        os.makedirs('data', exist_ok=True)
        # imagesディレクトリの作成・管理は不要になったので削除

        self.init_ui()
        self.load_articles_by_date(self.calendar.selectedDate())
        self.calendar.update()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # 左側パネル
        left_widget = QWidget()
        left_widget.setFixedWidth(300)
        left_layout = QVBoxLayout(left_widget)
        self.calendar = MarkCalendar()
        self.calendar.clicked.connect(self.load_articles_by_date)
        self.calendar.currentPageChanged.connect(lambda: self.calendar.update())
        left_layout.addWidget(self.calendar)

        self.status_label = QLabel("待機中")
        self.status_label.setStyleSheet("color: #7f8c8d; font-size: 11px;")
        left_layout.addWidget(self.status_label)

        self.btn_fetch = QPushButton("新着記事を取得")
        self.btn_fetch.setStyleSheet("background-color: #2ecc71; color: white; border-radius: 5px; padding: 10px;")
        self.btn_fetch.clicked.connect(self.start_fetch)
        left_layout.addWidget(self.btn_fetch)
        left_layout.addStretch()
        main_layout.addWidget(left_widget)

        # 右側パネル
        right_layout = QVBoxLayout()
        self.article_list = QListWidget()
        self.article_list.setItemDelegate(ArrowDelegate())
        self.article_list.setStyleSheet("""
            QListWidget { outline: none; border: 1px solid #ddd; background: white; }
            QListWidget::item { color: #2c3e50; }
        """)
        self.article_list.itemSelectionChanged.connect(self.on_selection_changed)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        right_layout.addWidget(QLabel("<b>記事一覧</b>"))
        right_layout.addWidget(self.article_list, 2)
        right_layout.addWidget(QLabel("<b>本文</b>"))
        right_layout.addWidget(self.browser, 3)
        main_layout.addLayout(right_layout)

    def on_selection_changed(self):
        items = self.article_list.selectedItems()
        if items:
            self.display_article(items[0])

    def start_fetch(self):
        self.btn_fetch.setEnabled(False)
        self.worker = FetchWorker()
        self.worker.progress.connect(self.status_label.setText)
        self.worker.finished.connect(self.on_fetch_finished)
        self.worker.start()

    def on_fetch_finished(self):
        self.btn_fetch.setEnabled(True)
        self.status_label.setText("更新完了")
        self.calendar.update()
        self.load_articles_by_date(self.calendar.selectedDate())

    def load_articles_by_date(self, qdate):
        self.article_list.clear()
        date_path = f"data/{qdate.year()}/{str(qdate.month()).zfill(2)}/{str(qdate.day()).zfill(2)}"
        if not os.path.exists(date_path):
            self.browser.setHtml("<div style='color:gray; padding:20px;'>記事はありません。</div>")
            return
        files = sorted(os.listdir(date_path), reverse=True)
        for fname in files:
            if not fname.endswith('.json'):
                continue
            try:
                with open(os.path.join(date_path, fname), 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    item = QListWidgetItem(data['title'])
                    item.setData(Qt.ItemDataRole.UserRole, data)
                    self.article_list.addItem(item)
            except:
                pass
        if self.article_list.count() > 0:
            self.article_list.setCurrentRow(0)

    def display_article(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        html = f"""
        <body style='font-family:sans-serif; padding:15px;'>
            <div style='color:#7f8c8d;font-size:12px;'>{data.get('date', '')} | {data['domain']}</div>
            <h1 style='margin-top:5px; font-size:20px;'>{data['title']}</h1>
            <p><a href='{data['link']}' style='color:#3498db;'>➔ ブラウザで開く</a></p>
            <hr style='border:0; border-top:1px solid #eee;'>
            <div style='font-size:15px; line-height:1.6;'>{data['summary']}</div>
        </body>
        """
        self.browser.setHtml(html)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MyRSS()
    window.show()
    sys.exit(app.exec())
