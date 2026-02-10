import streamlit as st
import pandas as pd
import re
from datetime import datetime
import io

# --- КОНФИГУРАЦИЯ ---
st.set_page_config(page_title="GMP Cross-Check (Manual Mode)", layout="wide")

# --- ФУНКЦИИ ---
def clean_text(text):
    return str(text).strip() if not pd.isna(text) else ""

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
    return "Unknown", None

def extract_drugs_gmp(drug_text):
    if pd.isna(drug_text): return []
    text = str(drug_text)
    text = re.sub(r'\n', ';', text).replace('1)', ';').replace('2)', ';')
    if ';' not in text and ',' in text: text = text.replace(',', ';')
    return [d.strip().lower() for d in text.split(';') if len(d.strip()) > 2]

def find_header_row_idx(df, keywords):
    """Ищет индекс строки с заголовками"""
    for i in range(min(30, len(df))):
        row_text = " ".join([str(x).lower() for x in df.iloc[i].values])
        if any(k in row_text for k in keywords): return i
    return None

def load_file_raw(uploaded_file):
    """Читает файл максимально 'сырым' образом"""
    try:
        if uploaded_file.name.lower().endswith('.csv'):
            # Пробуем разные кодировки
            for enc in ['utf-8', 'cp1251', 'latin1']:
                try:
                    uploaded_file.seek(0)
                    return pd.read_csv(uploaded_file, encoding=enc, sep=None, engine='python')
                except: continue
        else:
            return pd.read_excel(uploaded_file, header=None)
    except Exception as e:
        return None
    return None

def preprocess_dataframe(df, keywords_hint):
    """Пытается найти заголовок и установить его"""
    header_idx = find_header_row_idx(df, keywords_hint)
    if header_idx is not None:
        df.columns = df.iloc[header_idx]
        df = df.iloc[header_idx+1:].reset_index(drop=True)
        # Убираем дубликаты колонок, если есть
        df = df.loc[:, ~df.columns.duplicated()]
        return df, True
    else:
        # Если заголовок не нашли, даем имена Col_0, Col_1...
        df.columns = [f"Col_{i}: {str(v)[:20]}..." for i, v in enumerate(df.iloc[0])]
        return df, False

def highlight_rows(row):
    color = row.get('_bg', '#ffffff') 
    return [f'background-color: {color}'] * len(row)

# --- ИНТЕРФЕЙС ---
st.title("🛠️ GMP Cross-Check: Ручная настройка")
st.markdown("Если автоматика ошибается, укажите колонки вручную.")

col_main1, col_main2 = st.columns(2)

# === БЛОК 1: РУ (РЕГИСТРАЦИЯ) ===
with col_main1:
    st.header("1. Список РУ (Препараты)")
    file_reg = st.file_uploader("Загрузить Excel/CSV", key="reg")
    
    df_reg = None
    col_name_reg = None
    col_mfg_reg = None
    
    if file_reg:
        df_raw_reg = load_file_raw(file_reg)
        if df_raw_reg is not None:
            # Пытаемся найти заголовки
            df_reg, found = preprocess_dataframe(df_raw_reg, ["торговое", "наименование", "лекарственная"])
            
            st.caption("Предпросмотр таблицы (первые 3 строки):")
            st.dataframe(df_reg.head(3), use_container_width=True)
            
            st.error("👇 ВЫБЕРИТЕ КОЛОНКИ НИЖЕ:")
            cols_reg = list(df_reg.columns)
            
            # Пытаемся угадать индекс для селектора
            idx_n = next((i for i, c in enumerate(cols_reg) if 'наименование' in str(c).lower()), 0)
            idx_m = next((i for i, c in enumerate(cols_reg) if 'производител' in str(c).lower()), 0)

            col_name_reg = st.selectbox("В какой колонке НАЗВАНИЕ?", cols_reg, index=idx_n, key="s1")
            col_mfg_reg = st.selectbox("В какой колонке ПРОИЗВОДИТЕЛЬ?", cols_reg, index=idx_m, key="s2")
        else:
            st.error("Ошибка чтения файла")

# === БЛОК 2: GMP (ИНОСТРАННЫЕ) ===
with col_main2:
    st.header("2. База GMP")
    file_gmp = st.file_uploader("Загрузить Excel/CSV", key="gmp")
    
    df_gmp = None
    col_list_gmp = None
    col_date_gmp = None
    col_mfg_gmp = None
    
    if file_gmp:
        df_raw_gmp = load_file_raw(file_gmp)
        if df_raw_gmp is not None:
            df_gmp, found = preprocess_dataframe(df_raw_gmp, ["перечень", "производител"])
            
            st.caption("Предпросмотр таблицы (первые 3 строки):")
            st.dataframe(df_gmp.head(3), use_container_width=True)
            
            st.error("👇 ВЫБЕРИТЕ КОЛОНКИ НИЖЕ:")
            cols_gmp = list(df_gmp.columns)
            
            # Угадываем индексы
            idx_l = next((i for i, c in enumerate(cols_gmp) if 'перечень' in str(c).lower()), 0)
            idx_d = next((i for i, c in enumerate(cols_gmp) if 'срок' in str(c).lower()), 0)
            idx_mf = next((i for i, c in enumerate(cols_gmp) if 'производител' in str(c).lower()), 0)

            col_list_gmp = st.selectbox("В какой колонке СПИСОК ПРЕПАРАТОВ?", cols_gmp, index=idx_l, key="s3")
            col_date_gmp = st.selectbox("В какой колонке СРОК ДЕЙСТВИЯ?", cols_gmp, index=idx_d, key="s4")
            col_mfg_gmp = st.selectbox("В какой колонке ПРОИЗВОДИТЕЛЬ?", cols_gmp, index=idx_mf, key="s5")
        else:
            st.error("Ошибка чтения файла")

# === БЛОК 3: ЗАПУСК ===
st.divider()
if st.button("🚀 ЗАПУСТИТЬ АНАЛИЗ", type="primary"):
    if df_reg is not None and df_gmp is not None:
        with st.spinner("Анализируем..."):
            
            # 1. СОЗДАЕМ БАЗУ ЗНАНИЙ GMP
            gmp_db = []
            for _, row in df_gmp.iterrows():
                try:
                    status, dt = parse_date_status(row[col_date_gmp])
                    drugs = extract_drugs_gmp(row[col_list_gmp])
                    mfg = clean_text(row[col_mfg_gmp]).lower()
                    for d in drugs:
                        gmp_db.append({'drug': d, 'mfg': mfg, 'status': status, 'date': dt})
                except: continue # Пропускаем битые строки
            
            df_lookup = pd.DataFrame(gmp_db)
            
            if df_lookup.empty:
                st.error("Не удалось извлечь ни одного препарата из базы GMP. Проверьте выбор колонки 'Список препаратов'.")
            else:
                # 2. ПРОВЕРЯЕМ СПИСОК РУ
                results = []
                for _, row in df_reg.iterrows():
                    reg_name = clean_text(row[col_name_reg])
                    reg_mfg = clean_text(row[col_mfg_reg])
                    
                    match_status = "❌ GMP NOT FOUND"
                    match_details = "Нет действующего сертификата"
                    bg_color = "#FECACA"
                    
                    # Логика поиска (First Word Match)
                    tokens = re.split(r'[ \-\(\)\.\,]+', reg_name.lower())
                    search_key = next((t for t in tokens if len(t) > 2), "")
                    
                    if search_key:
                        candidates = df_lookup[df_lookup['drug'].str.contains(search_key, regex=False, na=False)]
                        if not candidates.empty:
                            active = candidates[candidates['status'] == 'Active']
                            if not active.empty:
                                best = active.iloc[0]
                                match_status = "✅ OK"
                                match_details = f"Действует до {best['date'].strftime('%d.%m.%Y')}"
                                bg_color = "#D1FAE5"
                            else:
                                match_status = "⚠️ EXPIRED"
                                match_details = "Сертификат истек"
                                bg_color = "#FEF3C7"
                    
                    results.append({
                        'Препарат (РУ)': reg_name,
                        'Статус': match_status,
                        'Инфо': match_details,
                        'Производитель': reg_mfg,
                        '_bg': bg_color
                    })
                
                df_final = pd.DataFrame(results)
                
                # 3. ВЫВОД
                st.success("Готово!")
                
                # Метрики
                ok_cnt = len(df_final[df_final['Статус'].str.contains("OK")])
                k1, k2 = st.columns(2)
                k1.metric("Всего проверено", len(df_final))
                k2.metric("Разрешен ввоз", ok_cnt)
                
                # Таблица
                styler = df_final.style.apply(highlight_rows, axis=1)
                st.dataframe(
                    styler,
                    column_config={"_bg": None},
                    use_container_width=True,
                    height=800
                )
                
                # Скачивание
                csv = df_final.drop(columns=['_bg']).to_csv(index=False).encode('utf-8-sig')
                st.download_button("Скачать результат (Excel/CSV)", csv, "report.csv", "text/csv", type="primary")

    else:
        st.warning("Сначала загрузите файлы и выберите колонки.")
