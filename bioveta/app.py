import streamlit as st
import pandas as pd
import re
from datetime import datetime

# --- НАСТРОЙКИ ---
st.set_page_config(page_title="GMP Check: 18 Drugs", layout="wide")

# --- ФУНКЦИИ ---
def clean_header(df):
    """Чистит заголовки"""
    df.columns = [str(c).strip() if pd.notna(c) and str(c).strip() != "" else f"Col_{i}" for i, c in enumerate(df.columns)]
    return df

def find_header_row(df, keywords):
    """Ищет строку заголовка"""
    for i in range(min(50, len(df))):
        row_text = " ".join([str(x).lower() for x in df.iloc[i].values])
        if sum(1 for k in keywords if k in row_text) >= 1:
            return i
    return None

def load_file(uploaded_file, file_role):
    """Читает файл в зависимости от его роли"""
    try:
        df = None
        # Чтение
        if uploaded_file.name.lower().endswith('.csv'):
            for enc in ['utf-8', 'cp1251', 'latin1']:
                try:
                    uploaded_file.seek(0)
                    df = pd.read_csv(uploaded_file, encoding=enc, sep=None, engine='python')
                    if df.shape[1] > 1: break
                except: continue
        else:
            df = pd.read_excel(uploaded_file, header=None)
        
        if df is None: return None, "Ошибка чтения"

        # Поиск заголовков по ключевым словам
        keywords = []
        if file_role == "TARGET": # Ваши 18 препаратов
            keywords = ["торговое", "наименование", "препарат"]
        else: # База GMP
            keywords = ["перечень", "производител", "срок"]
            
        idx = find_header_row(df, keywords)
        
        if idx is not None:
            df.columns = df.iloc[idx]
            df = df.iloc[idx+1:].reset_index(drop=True)
            df = clean_header(df)
            return df, None
            
        return clean_header(df), "Заголовки не найдены (но файл прочитан)"

    except Exception as e:
        return None, str(e)

def get_col(df, keywords):
    """Ищет колонку по ключевым словам"""
    for col in df.columns:
        if any(k in str(col).lower() for k in keywords):
            return col
    return None

def parse_date(date_str):
    if pd.isna(date_str): return "Нет данных", None
    text = str(date_str).lower()
    if "истек" in text: return "Expired", None
    match = re.search(r'(\d{2}\.\d{2}\.\d{4})', text)
    if match:
        try:
            d = datetime.strptime(match.group(1), '%d.%m.%Y')
            return ("Active", d) if d > datetime.now() else ("Expired", d)
        except: pass
    return "Active", None

def extract_drugs(text):
    if pd.isna(text): return []
    s = str(text)
    s = re.sub(r'\n', ';', s).replace('1)', ';').replace('2)', ';')
    if ';' not in s and ',' in s: s = s.replace(',', ';')
    return [d.strip().lower() for d in s.split(';') if len(d.strip()) > 2]

# --- ИНТЕРФЕЙС ---
st.title("🎯 GMP Аудит: Проверка списка (18 шт)")

c1, c2 = st.columns(2)
f_target = c1.file_uploader("1. ЗАГРУЗИТЕ ВАШ СПИСОК (18 строк)", key="t")
f_db = c2.file_uploader("2. ЗАГРУЗИТЕ БАЗУ GMP (Большую)", key="db")

if f_target and f_db:
    with st.spinner("Анализ..."):
        # 1. Читаем файлы
        df_target, m1 = load_file(f_target, "TARGET")
        df_db, m2 = load_file(f_db, "DB")
        
        if df_target is None or df_db is None:
            st.error("Ошибка чтения файлов.")
        else:
            # 2. Определяем колонки
            # В списке 18 препаратов
            col_t_name = get_col(df_target, ["торговое", "наименование", "препарат"]) or df_target.columns[0]
            col_t_mfg = get_col(df_target, ["производител", "фирма", "держатель"]) or df_target.columns[1]
            
            # В базе GMP
            col_db_list = get_col(df_db, ["перечень", "продукция"]) or df_db.columns[-1]
            col_db_mfg = get_col(df_db, ["производител", "фирма"]) or df_db.columns[1]
            col_db_date = get_col(df_db, ["срок", "дата"])

            # 3. Собираем базу для поиска (Lookup)
            lookup = []
            for _, row in df_db.iterrows():
                try:
                    st_val, dt = parse_date(row[col_db_date] if col_db_date else None)
                    drugs = extract_drugs(row[col_db_list])
                    mfg = str(row[col_db_mfg]).strip()
                    for d in drugs:
                        lookup.append({'d': d, 'mfg': mfg, 's': st_val, 'dt': dt})
                except: continue
            
            df_lookup = pd.DataFrame(lookup)
            
            # 4. Проверяем ВАШИ 18 СТРОК
            results = []
            for _, row in df_target.iterrows():
                # Данные из вашего файла
                target_name = str(row[col_t_name]).strip()
                target_mfg = str(row[col_t_mfg]).strip()
                
                # Логика поиска (по первому слову названия)
                tokens = re.split(r'[ \-\(\)\.\,]+', target_name.lower())
                key = next((t for t in tokens if len(t) > 2), "")
                
                status = "❌ GMP NOT FOUND"
                details = "Сертификат не найден"
                bg = "#FECACA" # Красный
                
                if key and not df_lookup.empty:
                    # Ищем совпадение
                    hits = df_lookup[df_lookup['d'].str.contains(key, regex=False, na=False)]
                    if not hits.empty:
                        # Проверяем статус
                        active = hits[hits['s'] == 'Active']
                        if not active.empty:
                            best = active.iloc[0]
                            status = "✅ OK"
                            date_str = best['dt'].strftime('%d.%m.%Y') if best['dt'] else "Активен"
                            details = f"GMP до {date_str}"
                            bg = "#D1FAE5" # Зеленый
                        else:
                            status = "⚠️ EXPIRED"
                            details = "Сертификат истек"
                            bg = "#FEF3C7" # Желтый
                
                results.append({
                    'Название препарата': target_name,
                    'Фирма (из вашего файла)': target_mfg,
                    'Статус': status,
                    'Детали': details,
                    '_bg': bg
                })
            
            final_df = pd.DataFrame(results)
            
            # 5. Вывод
            st.success(f"Готово! Проверено препаратов: {len(final_df)}")
            
            def color_rows(row):
                return [f'background-color: {row["_bg"]}'] * len(row)

            st.dataframe(
                final_df.style.apply(color_rows, axis=1),
                column_config={"_bg": None},
                use_container_width=True,
                height=800
            )
            
            csv = final_df.drop(columns=['_bg']).to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 Скачать результат (Excel)", csv, "report_18_drugs.csv", "text/csv", type="primary")
