import streamlit as st
import pandas as pd
import re
from datetime import datetime
import io

# --- КОНФИГУРАЦИЯ ---
st.set_page_config(page_title="Reg vs GMP Cross-Check", layout="wide")

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
    """Парсинг списка из GMP файла (ячейка с кучей текста)"""
    if pd.isna(drug_text): return []
    text = str(drug_text).replace('\n', ';').replace('1)', ';').replace('2)', ';')
    return [d.strip().lower() for d in text.split(';') if len(d.strip()) > 2]

def find_header_smart(df, keywords):
    for i in range(min(20, len(df))):
        row = df.iloc[i].astype(str).str.lower().to_string()
        if any(k in row for k in keywords): return i
    return None

def load_file_smart(uploaded_file, file_type="unknown"):
    try:
        if uploaded_file.name.lower().endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file, header=None) # Читаем без хедера сначала
        
        # Определение типа файла по ключевым словам
        if file_type == "REGISTRY": # Файл с 18 препаратами
            idx = find_header_smart(df, ["торговое наименование", "международное"])
        else: # Файл GMP
            idx = find_header_smart(df, ["перечень", "производител"])
            
        if idx is not None:
            df.columns = df.iloc[idx]
            df = df.iloc[idx+1:].reset_index(drop=True)
            return df, None
        return df, "Заголовки не найдены (автоматический режим)"
    except Exception as e:
        return None, str(e)

# --- ИНТЕРФЕЙС ---
st.title("⚖️ Cross-Check: Регистрация vs GMP")
st.markdown("Сверка списка **Зарегистрированных препаратов (РУ)** с наличием **Сертификата GMP**.")

col1, col2 = st.columns(2)
with col1:
    st.info("1. Файл с препаратами (РУ)")
    file_reg = st.file_uploader("Загрузить список (18 препаратов)", key="reg")
with col2:
    st.info("2. Файл GMP (Иностранные)")
    file_gmp = st.file_uploader("Загрузить базу GMP", key="gmp")

if st.button("ПРОВЕРИТЬ ЛЕГИТИМНОСТЬ ВВОЗА", type="primary"):
    if file_reg and file_gmp:
        with st.spinner("Сопоставление баз данных..."):
            # 1. ЗАГРУЗКА
            df_reg, err1 = load_file_smart(file_reg, "REGISTRY")
            df_gmp, err2 = load_file_smart(file_gmp, "GMP")
            
            if err1 or err2:
                st.error(f"Ошибка чтения: {err1 or err2}")
            else:
                # 2. ПОИСК КОЛОНОК
                # В файле РУ ищем 'Торговое наименование'
                col_name_reg = next((c for c in df_reg.columns if 'торговое' in str(c).lower()), None)
                col_mfg_reg = next((c for c in df_reg.columns if 'производител' in str(c).lower()), None)
                
                # В файле GMP ищем 'Перечень' и 'Срок'
                col_list_gmp = next((c for c in df_gmp.columns if 'перечень' in str(c).lower()), None)
                col_date_gmp = next((c for c in df_gmp.columns if 'срок' in str(c).lower()), None)
                col_mfg_gmp = next((c for c in df_gmp.columns if 'производител' in str(c).lower()), None)

                if not (col_name_reg and col_list_gmp):
                    st.error("Не найдены ключевые колонки ('Торговое наименование' в файле 1 или 'Перечень' в файле 2).")
                else:
                    # 3. ПОДГОТОВКА БАЗЫ GMP (lookup dictionary)
                    gmp_db = []
                    for _, row in df_gmp.iterrows():
                        status, dt = parse_date_status(row[col_date_gmp] if col_date_gmp else None)
                        drugs = extract_drugs_gmp(row[col_list_gmp])
                        mfg = clean_text(row[col_mfg_gmp]).lower()
                        for d in drugs:
                            gmp_db.append({'drug': d, 'mfg': mfg, 'status': status, 'date': dt})
                    
                    df_gmp_lookup = pd.DataFrame(gmp_db)

                    # 4. АНАЛИЗ СПИСКА РУ
                    results = []
                    for _, row in df_reg.iterrows():
                        reg_name = clean_text(row[col_name_reg])
                        reg_mfg = clean_text(row[col_mfg_reg]) if col_mfg_reg else ""
                        
                        # Логика поиска:
                        # Ищем совпадение названия препарата в базе GMP
                        # 1. Точное/частичное совпадение имени
                        # 2. (Опционально) Совпадение производителя
                        
                        match_status = "❌ GMP NOT FOUND"
                        match_details = "Препарат зарегистрирован, но GMP не найден"
                        bg_color = "#FECACA" # Red
                        
                        if not df_gmp_lookup.empty:
                            # Ищем по названию (первые 5 букв для надежности, т.к. написание может отличаться)
                            # Например "Биокан" vs "Биокан DHPPi"
                            search_key = reg_name.lower().split(' ')[0][:5] 
                            
                            candidates = df_gmp_lookup[df_gmp_lookup['drug'].str.contains(search_key, regex=False, na=False)]
                            
                            # Если нашли кандидатов, проверяем статус
                            if not candidates.empty:
                                # Берем лучший матч (Active)
                                active_matches = candidates[candidates['status'] == 'Active']
                                if not active_matches.empty:
                                    best = active_matches.iloc[0]
                                    match_status = "✅ OK: IMPORT ALLOWED"
                                    match_details = f"GMP valid until {best['date'].strftime('%d.%m.%Y')}"
                                    bg_color = "#D1FAE5" # Green
                                else:
                                    match_status = "⚠️ WARNING: GMP EXPIRED"
                                    match_details = "GMP сертификат найден, но срок истек"
                                    bg_color = "#FEF3C7" # Yellow
                        
                        results.append({
                            'Препарат (РУ)': reg_name,
                            'Производитель (РУ)': reg_mfg,
                            'Статус GMP': match_status,
                            'Комментарий': match_details,
                            '_bg': bg_color
                        })
                    
                    df_final = pd.DataFrame(results)
                    
                    # 5. ВЫВОД
                    success_count = len(df_final[df_final['Статус GMP'].str.contains("OK")])
                    risk_count = len(df_final) - success_count
                    
                    m1, m2 = st.columns(2)
                    m1.metric("Всего препаратов в РУ", len(df_final))
                    m2.metric("С действующим GMP (Ввоз разрешен)", success_count)
                    
                    st.subheader("Результат сверки")
                    
                    # Раскраска таблицы
                    def highlight_rows(row):
                        return [f'background-color: {row["_bg"]}'] * len(row)

                    st.dataframe(
                        df_final.drop(columns=['_bg']).style.apply(highlight_rows, axis=1),
                        use_container_width=True,
                        height=600
                    )
                    
                    # Скачивание
                    csv = df_final.drop(columns=['_bg']).to_csv(index=False).encode('utf-8-sig')
                    st.download_button("Скачать отчет сверки", csv, "cross_check_report.csv", "text/csv", type="primary")

    else:
        st.warning("Пожалуйста, загрузите оба файла.")
