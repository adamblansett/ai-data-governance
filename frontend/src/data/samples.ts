import type { FieldRule } from '../types/governance';

export const SAMPLE_PII_TEXT =
  'Patient: Dr. Elena Vance | Email: elena.vance@northwind.io | Phone: (415) 555-0199 | ' +
  'SSN: 123-45-6789 | Billing Card: 4532-0151-1283-0366 | Employer: Northwind Health LLC | ' +
  'Address: 742 Evergreen Ave.';

export const SAMPLE_PII_RECORDS = [
  {
    id: 'cust-101',
    full_name: 'Elena Vance',
    email: 'elena.vance@northwind.io',
    phone: '+1-415-555-0199',
    ssn: '123-45-6789',
    address: '742 Evergreen Ave',
  },
  {
    id: 'cust-102',
    full_name: 'Marcus Cole',
    email: 'marcus.cole@globex.io',
    phone: '(212) 555-0144',
    ssn: '987-65-4321',
    address: '100 Main Street',
  },
];

export const SAMPLE_DEDUP_RECORDS = [
  {
    id: 'crm-101',
    name: 'Jane Doe',
    email: 'jane.doe@acme.com',
    phone: '(555) 234-5678',
    company: 'Acme',
    updated_at: '2026-02-01T10:00:00Z',
  },
  {
    id: 'crm-102',
    name: 'Doe, Jane',
    email: 'jane.doe@acme.com',
    phone: '+1-555-234-5678',
    company: 'Acme Corporation',
    tier: 'Enterprise',
    updated_at: '2026-06-14T15:30:00Z',
  },
  {
    id: 'crm-103',
    name: 'Alicia Smith',
    email: 'alice.smith@northwind.io',
    phone: '415-555-0180',
    company: 'Northwind Health',
    updated_at: '2026-03-10T09:00:00Z',
  },
  {
    id: 'crm-104',
    name: 'Alice Smith',
    email: 'alice.smith@northwind.io',
    phone: '+14155550180',
    company: 'Northwind Health LLC',
    updated_at: '2026-07-02T11:00:00Z',
  },
];

export const SAMPLE_NORMALIZER_RECORDS = [
  {
    id: 'row-1',
    email: '  ALICE.SMITH@Acme.COM ',
    phone: '(415) 555-0199',
    address: '123 main street, austin, texas 78701',
    country: 'United States',
    notes: 'N/A',
    bio: '  Lead   Data   Architect ',
    signup_date: 'Nov 24, 2026',
  },
  {
    id: 'row-2',
    email: 'bob.jones@northwind.io',
    phone: '555-234-5678',
    address: '450 oak avenue, new york, ny 10001',
    country: 'Canada',
    notes: 'null',
    bio: 'Staff   Engineer',
    signup_date: '2026/10/05',
  },
  {
    id: 'row-3',
    email: 'not-an-email',
    phone: '123',
    address: '99 pine road, denver, co 80202',
    country: 'Mars',
    notes: 'Requires follow-up',
    bio: 'Analyst',
    signup_date: 'invalid-date',
  },
];

export const SAMPLE_NORMALIZER_RULES: FieldRule[] = [
  { field: 'email', kind: 'email' },
  { field: 'phone', kind: 'phone', default_country_code: '+1' },
  { field: 'address', kind: 'address' },
  {
    field: 'country',
    kind: 'taxonomy',
    taxonomy_map: { 'united states': 'US', usa: 'US', canada: 'CA' },
  },
  { field: 'notes', kind: 'nulls' },
  { field: 'bio', kind: 'whitespace' },
  { field: 'signup_date', kind: 'date_iso' },
];

export const SAMPLE_SCHEMA_DDL = `CREATE TABLE customers (
    id BIGINT PRIMARY KEY,
    email TEXT NOT NULL,
    ssn TEXT,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT REFERENCES customers(id),
    legacy_org_id BIGINT REFERENCES missing_orgs(id),
    total NUMERIC(10, 2),
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE raw_events_staging (
    payload TEXT
);

CREATE INDEX idx_orders_created ON orders (created_at);`;

export const SAMPLE_SCHEMA_CATALOG = [
  {
    name: 'customers',
    row_count: 85000,
    seq_scans: 4200,
    idx_scans: 150,
    retention_days: 90,
    oldest_record_days: 410,
  },
  {
    name: 'orders',
    row_count: 140000,
    foreign_keys: [
      { column: 'customer_id', ref_table: 'customers', ref_column: 'id', orphan_count: 12 },
      { column: 'legacy_org_id', ref_table: 'missing_orgs', ref_column: 'id' },
    ],
    indexes: [{ name: 'idx_orders_created', columns: ['created_at'], scans: 0 }],
  },
];
