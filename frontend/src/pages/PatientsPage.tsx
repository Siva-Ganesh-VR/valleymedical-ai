import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { LoadState } from "../components/ui";
import { useLoad } from "../hooks";
import { usDate } from "../labels";

export default function PatientsPage() {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 250);
    return () => clearTimeout(t);
  }, [query]);
  const { data, loading, error } = useLoad(() => api.patients(debounced), [debounced]);

  return (
    <section>
      <header className="page-head">
        <h1>Patients</h1>
        <p className="lede">Records are read from Meditab IMS. Nothing here changes Meditab.</p>
      </header>
      <label className="search">
        <span className="visually-hidden">Search patients</span>
        <input type="search" placeholder="Search by name, MRN or date of birth" value={query}
               onChange={(e) => setQuery(e.target.value)} />
      </label>
      <LoadState loading={loading && !data} error={error} />
      {data && data.length === 0 && <p className="empty">No patients match "{debounced}". Try a last name or MRN.</p>}
      {data && data.length > 0 && (
        <table className="table">
          <thead>
            <tr><th>Name</th><th>MRN</th><th>Date of birth</th><th>Sex</th></tr>
          </thead>
          <tbody>
            {data.map((p) => (
              <tr key={p.patient_id}>
                <td><Link to={`/patients/${p.patient_id}`}>{p.last_name}, {p.first_name}</Link></td>
                <td className="num">{p.mrn}</td>
                <td className="num">{usDate(p.dob)}</td>
                <td>{p.sex}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="fine">Two patients share the same name and date of birth on purpose, to show why matching uses identifiers, not names.</p>
    </section>
  );
}
