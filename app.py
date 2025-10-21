
import io
import pandas as pd
import streamlit as st

# Optional (installed via requirements). If not installed, we fall back gracefully.
try:
    import tldextract
    HAS_TLDEXTRACT = True
except Exception:
    HAS_TLDEXTRACT = False

st.set_page_config(page_title="Domain Intersector (Cherry-pick by Company)", page_icon="🏷️", layout="centered")

st.title("🏷️ Domain Intersector")
st.caption("Upload two **.xlsx** files. We'll take all email domains from **List A** and return **all contacts from List B** that share those domains.")

with st.expander("How it works / assumptions", expanded=False):
    st.markdown("""
    - **Goal:** Use your smaller **List A** of contacts to cherry‑pick **all** contacts at the same companies from **List B**.
    - We **derive email domains** from both lists and keep **every row in List B** whose domain is found in List A's domain set.
    - Supports **registered-domain** extraction (e.g., `eu.mail.acme.co.uk` → `acme.co.uk`) if `tldextract` is installed.
    - Only **.xlsx** is supported (uses `openpyxl`). Convert CSVs to XLSX if needed.
    """)

st.sidebar.header("Options")
trim_spaces = st.sidebar.checkbox("Trim surrounding whitespace", value=True)
case_insensitive = st.sidebar.checkbox("Lowercase domains", value=True)
use_registered_domain = st.sidebar.checkbox("Reduce to registered domain (via tldextract)", value=True if HAS_TLDEXTRACT else False, disabled=not HAS_TLDEXTRACT)
dedupe_domains_A = st.sidebar.checkbox("De‑dupe domain list from A", value=True)
dedupe_contacts_B = st.sidebar.checkbox("De‑dupe contacts in B by Email", value=False)
output_add_domain_col = st.sidebar.checkbox("Include derived 'domain' column in results", value=True)

def read_xlsx(label_prefix):
    uploaded = st.file_uploader(f"Upload {label_prefix} (.xlsx only)", type=["xlsx"], key=f"{label_prefix}_uploader")
    if not uploaded:
        return None, None
    try:
        xl = pd.ExcelFile(uploaded, engine="openpyxl")
        sheet = st.selectbox(f"{label_prefix}: choose sheet", options=xl.sheet_names, key=f"{label_prefix}_sheet")
        df = xl.parse(sheet_name=sheet, engine="openpyxl")
    except Exception as e:
        st.error(f"Failed to read Excel with openpyxl: {e}")
        return None, None
    # Guess an email column
    email_like = [c for c in df.columns if "email" in str(c).lower() or "e-mail" in str(c).lower() or "mail" == str(c).lower()]
    email_col = st.selectbox(f"{label_prefix}: Email column", options=list(df.columns), index=(df.columns.get_loc(email_like[0]) if email_like else 0), key=f"{label_prefix}_email_col")
    st.caption(f"{label_prefix} preview (first 10 rows):")
    st.dataframe(df.head(10), use_container_width=True)
    return (df, email_col)

def to_registered_domain(domain: str) -> str | None:
    if not isinstance(domain, str) or len(domain) == 0:
        return None
    if not HAS_TLDEXTRACT:
        return domain
    ext = tldextract.extract(domain)
    if not ext.registered_domain:
        # tldextract couldn't parse; fall back to raw
        return domain
    return ext.registered_domain

def email_to_domain(email: str) -> str | None:
    if not isinstance(email, str):
        return None
    s = email
    if trim_spaces:
        s = s.strip()
    if "@" not in s:
        return None
    dom = s.split("@", 1)[1].strip()
    if case_insensitive:
        dom = dom.lower()
    if use_registered_domain:
        dom = to_registered_domain(dom) or dom
    return dom

col1, col2 = st.columns(2)
with col1:
    a = read_xlsx("List A (small list)")
with col2:
    b = read_xlsx("List B (large contacts list)")

run = st.button("🎯 Cherry‑pick Contacts by Domain", type="primary", disabled=not (a and b and a[0] is not None and b[0] is not None))

if run and a and b and a[0] is not None and b[0] is not None:
    try:
        df_a, email_col_a = a
        df_b, email_col_b = b

        # Derive domains
        domains_a = df_a[email_col_a].map(email_to_domain)
        domains_b = df_b[email_col_b].map(email_to_domain)

        # Attach to dataframes for optional output
        df_a["_domain"] = domains_a
        df_b["_domain"] = domains_b

        # Filter invalid
        domA = domains_a.dropna()
        domB = domains_b.dropna()

        if dedupe_domains_A:
            domA = domA.drop_duplicates()

        if dedupe_contacts_B and "Email" in df_b.columns:
            df_b = df_b.drop_duplicates(subset=["Email"], keep="first")
            domB = df_b["_domain"].dropna()  # re-pull after de-dupe

        domain_set = set(domA.tolist())
        in_both_mask = df_b["_domain"].isin(domain_set)

        picked = df_b.loc[in_both_mask].copy()

        # Optionally include domain column
        if not output_add_domain_col and "_domain" in picked.columns:
            picked = picked.drop(columns=["_domain"])

        # Summary per domain
        summary = (
            df_b.loc[in_both_mask, ["_domain"]]
            .value_counts()
            .rename_axis("domain")
            .reset_index(name="contact_count_in_B")
        )

        # Also expose the raw domain list from A (after normalization)
        domains_from_A = pd.DataFrame(sorted(domain_set), columns=["domain"])

        st.success(f"Found **{len(picked)}** matching contact(s) across **{len(domain_set)}** domains from List A.")

        st.subheader("Preview: Cherry‑picked contacts from List B")
        st.dataframe(picked.head(20), use_container_width=True)

        # Downloads
        csv_contacts = picked.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download Contacts (CSV)", data=csv_contacts, file_name="picked_contacts_by_domain.csv", mime="text/csv")

        csv_summary = summary.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download Domain Summary (CSV)", data=csv_summary, file_name="domain_summary.csv", mime="text/csv")

        csv_domains = domains_from_A.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download Domains from A (CSV)", data=csv_domains, file_name="domains_from_A.csv", mime="text/csv")

        with st.expander("Diagnostics"):
            st.json({
                "email_col_a": email_col_a,
                "email_col_b": email_col_b,
                "trim_spaces": trim_spaces,
                "case_insensitive": case_insensitive,
                "use_registered_domain": use_registered_domain and HAS_TLDEXTRACT,
                "dedupe_domains_A": dedupe_domains_A,
                "dedupe_contacts_B": dedupe_contacts_B,
                "output_add_domain_col": output_add_domain_col,
                "rows_A": len(df_a),
                "rows_B": len(df_b),
                "unique_domains_from_A": len(domain_set),
                "picked_contacts": len(picked),
            })

    except Exception as e:
        st.exception(e)

st.markdown("---")
if not HAS_TLDEXTRACT:
    st.info("Tip: Enable **registered-domain** extraction by adding `tldextract>=3.1` to requirements.txt.")
