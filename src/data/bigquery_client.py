from google.cloud import bigquery
import pandas as pd
from typing import Dict, Optional
from pathlib import Path
from config.settings import config


class BigQueryClient:
    """Client for interacting with Google BigQuery with cost estimation."""

    def __init__(self, project_id: Optional[str] = None):
        """
        Initialize BigQuery client.

        Args:
            project_id: GCP project ID. If None, uses config default.
        """
        self.project_id = project_id or config.BIGQUERY_PROJECT
        if not self.project_id:
            raise ValueError(
                "BIGQUERY_PROJECT must be set in environment or passed to constructor"
            )

        self.client = bigquery.Client(project=self.project_id)
        print(f"Connected to BigQuery project: {self.project_id}")

    def estimate_query_cost(self, sql: str) -> Dict[str, float]:
        """
        Estimate query cost using dry run mode (FREE).

        This uses BigQuery's built-in dry run feature to get exact byte counts
        without actually executing the query.

        Args:
            sql: SQL query to estimate

        Returns:
            Dictionary with:
                - bytes_scanned: Exact number of bytes that will be scanned
                - gb_scanned: Gigabytes that will be scanned
                - cost_usd: Estimated cost in USD ($5 per TB)
        """
        job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)

        try:
            query_job = self.client.query(sql, job_config=job_config)

            bytes_scanned = query_job.total_bytes_processed
            gb_scanned = bytes_scanned / (1024**3)
            tb_scanned = bytes_scanned / (1024**4)
            cost_usd = tb_scanned * config.BIGQUERY_COST_PER_TB

            result = {
                "bytes_scanned": bytes_scanned,
                "gb_scanned": gb_scanned,
                "cost_usd": cost_usd,
            }

            # Warn if over threshold
            if gb_scanned > config.BIGQUERY_WARN_THRESHOLD_GB:
                print(f"⚠️  WARNING: Query will scan {gb_scanned:.2f} GB (${cost_usd:.4f})")
                print(f"   This exceeds the warning threshold of {config.BIGQUERY_WARN_THRESHOLD_GB} GB")
            else:
                print(f"✓ Query will scan {gb_scanned:.2f} GB (${cost_usd:.4f})")

            return result

        except Exception as e:
            print(f"Error estimating query cost: {e}")
            raise

    def preview_result_count(self, sql: str) -> int:
        """
        Estimate number of rows that will be returned.

        Wraps the query in a COUNT(*) to get approximate row count.
        This is fast and cheap to run.

        Args:
            sql: SQL query to estimate

        Returns:
            Approximate number of rows (rounded for large queries)
        """
        count_query = f"""
        SELECT COUNT(*) as row_count
        FROM ({sql})
        """

        try:
            result = self.client.query(count_query).result()
            row_count = list(result)[0].row_count

            # Format output for readability
            if row_count >= 1_000_000:
                print(f"Expected results: ~{row_count/1_000_000:.1f}M rows")
            elif row_count >= 1_000:
                print(f"Expected results: ~{row_count/1_000:.1f}K rows")
            else:
                print(f"Expected results: {row_count} rows")

            return row_count

        except Exception as e:
            print(f"Error previewing result count: {e}")
            raise

    def query(self, sql: str, show_estimate: bool = True) -> pd.DataFrame:
        """
        Execute query and return results as DataFrame.

        Args:
            sql: SQL query to execute
            show_estimate: Whether to show cost estimate before executing

        Returns:
            DataFrame with query results
        """
        if show_estimate:
            estimate = self.estimate_query_cost(sql)
            print(f"Executing query... (scanning {estimate['gb_scanned']:.2f} GB)")

        try:
            query_job = self.client.query(sql)
            df = query_job.to_dataframe()
            print(f"✓ Query completed. Retrieved {len(df):,} rows")
            return df

        except Exception as e:
            print(f"Error executing query: {e}")
            raise

    def export_to_csv(self, sql: str, output_path: str) -> str:
        """
        Export query results to CSV file.

        Args:
            sql: SQL query to execute
            output_path: Path to output CSV file

        Returns:
            Path to created file
        """
        print(f"Exporting query results to {output_path}...")
        df = self.query(sql)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        df.to_csv(output_path, index=False)
        print(f"✓ Exported {len(df):,} rows to {output_path}")

        return str(output_path)

    def export_to_parquet(self, sql: str, output_path: str) -> str:
        """
        Export query results to Parquet file (faster and smaller than CSV).

        Args:
            sql: SQL query to execute
            output_path: Path to output Parquet file

        Returns:
            Path to created file
        """
        print(f"Exporting query results to {output_path}...")
        df = self.query(sql)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        df.to_parquet(output_path, index=False)
        print(f"✓ Exported {len(df):,} rows to {output_path}")

        return str(output_path)

    def load_query_from_file(self, file_path: str) -> str:
        """
        Load SQL query from file.

        Args:
            file_path: Path to SQL file

        Returns:
            SQL query string
        """
        with open(file_path, "r") as f:
            sql = f.read()
        return sql

    def estimate_and_preview(self, sql: str) -> Dict[str, any]:
        """
        Convenience method to both estimate cost and preview row count.

        Args:
            sql: SQL query to analyze

        Returns:
            Dictionary with both cost estimate and row count
        """
        print("=" * 60)
        print("QUERY ANALYSIS")
        print("=" * 60)

        cost_estimate = self.estimate_query_cost(sql)
        row_count = self.preview_result_count(sql)

        result = {
            **cost_estimate,
            "estimated_rows": row_count,
        }

        print("=" * 60)
        return result
