"""Run with uv run python examples/portal_demo.py; leaves a table for the Portal."""
import os

import pandas as pd
from iristool import IRIStool


def main():
    data = pd.DataFrame({
        "Sample Number": [1, 2, 3],
        "Name": ["Ada", "Grace", "Linus"],
        "Score": [95.5, None, 88.0],
        "Active": pd.Series([True, False, pd.NA], dtype="boolean"),
        "Note": ["Loaded from pandas", "O'Reilly", "Unicode: café"],
    })
    sql = "SELECT Sample_Number, Name, Score, Active, Note FROM SQLUser.IRISTool_Demo ORDER BY Sample_Number"
    with IRIStool(
        host=os.getenv("IRIS_HOST", "localhost"),
        port=os.getenv("IRIS_PORT", "9091"),
        namespace=os.getenv("IRIS_NAMESPACE", "USER"),
        username=os.getenv("IRIS_USER", "_SYSTEM"),
        password=os.getenv("IRIS_PASSWORD", "SYS"),
    ) as db:
        print("Creating/replacing SQLUser.IRISTool_Demo with three sample rows.")
        db.df_to_table(data, "IRISTool_Demo", primary_key="Sample Number",
                       exist_ok=True, drop_if_exists=True, batch_size=2)
        result = db.fetch(sql)
        assert result["Name"].tolist() == data["Name"].tolist(), "Names did not round-trip"
        assert pd.isna(result.loc[1, "Score"]), "Missing score did not round-trip"
        assert pd.isna(result.loc[2, "Active"]), "Missing boolean did not round-trip"
        assert result.loc[2, "Note"] == "Unicode: café", "Unicode did not round-trip"
        print(result.to_string(index=False))

    print("\nPASS: imported and verified three rows. Table kept for Portal inspection.")
    print("In the IRIS Portal, open SQL and select namespace " + os.getenv("IRIS_NAMESPACE", "USER") + ".")
    print(sql + ";")
    print("To remove the demo later: DROP TABLE SQLUser.IRISTool_Demo;")


if __name__ == "__main__":
    main()
