import streamlit as st
import pandas as pd
import re
from datetime import datetime
import io

# --- НАСТРОЙКИ ---
st.set_page_config(page_title="GMP Auto-Audit V10", layout="wide")

# --- ФУНКЦИИ ---

def clean_header(df):
    """Чистит заголовки от мусора и пустот"""
    df.columns = [str(c).strip() if pd.notna(c) and str(c).strip() != "" else f"Col_{i}" for i, c in enumerate(df.columns)]
    return df

def find_header_row(df, keywords):
    """Ищет строку заголовка"""
    for i in range(min(50, len(df))):
        row_text = " ".join([str(x).lower() for x in df.iloc[i].values])
        if sum(1 for k in keywords if k in row_text) >= 1:
            return i
    return None

def load_smart(uploaded_file):
    """Читает файл и возвращает DataFrame + список найденных ключевых слов"""
    try:
        df = None
        if uploaded_file.name.lower().endswith('.csv'):
            for enc in ['utf-8', 'cp1251', 'latin1']:
                try:
                    uploaded_file.seek(0)
                    df = pd.read_csv(uploaded_file, encoding=enc, sep=None, engine='python')
                    if df.shape[1] > 1: break
                except: continue
        else:
            df = pd.read_excel(uploaded_file, header=None)
        
        if df is None: return None, "Error"

        # Пытаемся понять, что это за файл, по содержимому
        header_idx = find_header_row(df, ["торговое", "наименование", "перечень", "производител", "срок"])
        
        if header_idx is not None:
            df.columns = df.iloc[header_idx]
            df = df.iloc[header_idx+1:].reset_index(drop=True)
            df = clean_header(df)
            return df, "OK"
            
        df = clean_header(df)
        return df, "No Header"

    except Exception as e:
        return None, str(e)

def identify_file_type(df):
    """Определяет роль файла: это список РУ (Target) или база GMP (Database)?"""
    cols = " ".join([str(c).lower() for c in df.columns])
    
    # Признаки базы GMP
    score_gmp = 0
    if "перечень" in cols: score_gmp += 3
    if "срок" in cols: score_gmp += 2
    if "площадк" in cols: score_gmp += 2
    
    # Признаки списка РУ
    score_reg = 0
    if "торговое" in cols: score_reg += 3
    if "лекарственная" in cols: score_reg += 2
    if "мнн" in cols: score_reg += 1
    
    # Если непонятно по заголовкам, смотрим на размер
    # Список РУ обычно маленький, GMP база огромная
    if score_gmp == score_reg:
        if len(df) > 1000: return "GMP"
        else: return "REG"
        
    return "GMP" if score_gmp > score_reg else "REG"

def get_col_by_keyword(df, keywords):
    for col in df.columns:
        c_str = str(col).lower()
        if any(k in c_str for k in keywords):
            return col
    return None

def parse_date_status(date_str):
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
st.title("⚡ GMP Auto-Audit: Smart Filter")
st.markdown("Загрузите файлы в любом порядке. Система сама поймет, где ваши 18 препаратов, а где база GMP.")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Файл 1", key="f1")
f2 = c2.file_uploader("Файл 2", key="f2")

if f1 and f2:
    with st.spinner("Распознавание файлов и анализ..."):
        # 1. Загружаем оба файла
        df_a, msg_a = load_smart(f1)
        df_b, msg_b = load_smart(f2)
        
        if df_a is None or df_b is None:
            st.error("Ошибка чтения одного из файлов.")
        else:
            # 2. Определяем кто есть кто
            type_a = identify_file_type(df_a)
            type_b = identify_file_type(df_b)
            
            df_reg = None
            df_gmp = None
            
            # Логика распределения
            if type_a == "REG" and type_b == "GMP":
                df_reg, df_gmp = df_a, df_b
            elif type_a == "GMP" and type_b == "REG":
                df_reg, df_gmp = df_b, df_a
            else:
                # Если типы совпали, берем тот, что меньше, как REG
                if len(df_a) < len(df_b):
                    df_reg, df_gmp = df_a, df_b
                else:
                    df_reg, df_gmp = df_b, df_a
            
            # Сообщение пользователю
            st.info(f"📁 Файл списка препаратов (обработаем {len(df_reg)} строк) | 📚 База GMP (справочник из {len(df_gmp)} записей)")
            
            # 3. Находим колонки
            # РУ
            col_name = get_col_by_keyword(df_reg, ["торговое", "наименование", "препарат"]) or df_reg.columns[0]
            col_mfg_reg = get_col_by_keyword(df_reg, ["производител", "фирма", "держатель"])
            
            # GMP
            col_list = get_col_by_keyword(df_gmp, ["перечень", "продукция", "лекарствен"]) or df_gmp.columns[-1]
            col_mfg_gmp = get_col_by_keyword(df_gmp, ["производител", "фирма"]) or df_gmp.columns[1]
            col_date = get_col_by_keyword(df_gmp, ["срок", "дата", "окончание"])
            
            # 4. Создаем Lookup базу
            gmp_db = []
            for _, row in df_gmp.iterrows():
                try:
                    st_val, dt = parse_date_status(row[col_date] if col_date else None)
                    drugs = extract_drugs(row[col_list])
                    mfg = str(row[col_mfg_gmp]).strip().lower()
                    for d in drugs:
                        gmp_db.append({'d': d, 'm': mfg, 's': st_val, 'dt': dt})
                except: continue
            
            lookup = pd.DataFrame(gmp_db)
            
            # 5. Анализируем ТОЛЬКО df_reg (наши 18 строк)
            results = []
            for _, row in df_reg.iterrows():
                r_name = str(row[col_name]).strip()
                r_mfg = str(row[col_mfg_reg]).strip() if col_mfg_reg else ""
                
                # Логика поиска
                tokens = re.split(r'[ \-\(\)\.\,]+', r_name.lower())
                key = next((t for t in tokens if len(t) > 2), "")
                
                status = "❌ GMP NOT FOUND"
                details = "Сертификат не найден"
                bg = "#FECACA"
                
                if key and not lookup.empty:
                    hits = lookup[lookup['d'].str.contains(key, regex=False, na=False)]
                    if not hits.empty:
                        active = hits[hits['s'] == 'Active']
                        if not active.empty:
                            best = active.iloc[0]
                            status = "✅ OK"
                            date_str = best['dt'].strftime('%d.%m.%Y') if best['dt'] else "Активен"
                            details = f"Действует до {date_str}"
                            bg = "#D1FAE5"
                        else:
                            status = "⚠️ EXPIRED"
                            details = "Сертификат найден, но истек"
                            bg = "#FEF3C7"
                
                results.append({
                    'Препарат (РУ)': r_name,
                    'Статус': status,
                    'Детали': details,
                    'Производитель': r_mfg,
                    '_bg': bg
                })
            
            final_df = pd.DataFrame(results)
            
            # 6. Вывод
            def color_rows(row):
                return [f'background-color: {row["_bg"]}'] * len(row)

            st.dataframe(
                final_df.style.apply(color_rows, axis=1),
                column_config={"_bg": None},
                use_container_width=True,
                height=800
            )
            
            csv = final_df.drop(columns=['_bg']).to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 Скачать результат (только ваши препараты)", csv, "checked_18_items.csv", "text/csv", type="primary")
