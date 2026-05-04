"""
Analytics & Reporting Service (Async)
Provides detailed insights, trends, and exportable reports
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from bson import ObjectId
from core.logging_service import logger

async def get_analytics_summary(recruiter_id: str, db) -> Dict:
    """Get comprehensive analytics summary for a recruiter (Async)"""
    try:
        # Phase 6: Add query timeout to prevent slow queries
        MAX_QUERY_TIME_MS = 5000  # 5 seconds max
        
        # Get all jobs for this recruiter
        jobs = await db.jds.find(
            {"recruiter_id": recruiter_id, "is_deleted": {"$ne": True}}
        ).max_time_ms(MAX_QUERY_TIME_MS).to_list(length=1000)
        
        job_ids = [str(job["_id"]) for job in jobs]
        
        if not job_ids:
            return {
                "kpis": {
                    "total_jobs": 0, "active_jobs": 0,
                    "total_applications": 0, "avg_applications_per_job": 0,
                    "total_candidates_interviewed": 0, "interview_rate": 0,
                    "total_hired": 0, "hire_rate": 0
                },
                "status_distribution": {},
                "chart_data": {"labels": [], "values": []},
                "average_match_score": 0, "time_to_hire_days": 0, "bias_detection_count": 0,
                "application_rate": 0, "interview_rate": 0, "hire_rate": 0
            }
        
        # Get applications (with timeout)
        applications = await db.applications.find({"job_id": {"$in": job_ids}}).max_time_ms(MAX_QUERY_TIME_MS).to_list(length=5000)
        
        # Get interviews (with timeout)
        interviews = await db.interviews.find({"jd_id": {"$in": job_ids}}).max_time_ms(MAX_QUERY_TIME_MS).to_list(length=5000)
        
        # Calculate metrics
        total_jobs = len(jobs)
        total_applications = len(applications)
        total_interviews = len([i for i in interviews if i.get("completed_at")])
        total_hired = len([a for a in applications if a.get("status") == "Hired"])
        
        match_scores = [a.get("ai_match_score", 0) for a in applications if a.get("ai_match_score")]
        avg_match_score = sum(match_scores) / len(match_scores) if match_scores else 0
        
        time_to_hire = []
        for app in applications:
            if app.get("status") == "Hired" and app.get("applied_at") and app.get("updated_at"):
                try:
                    applied = datetime.fromisoformat(app["applied_at"].replace('Z', '+00:00'))
                    hired = datetime.fromisoformat(app["updated_at"].replace('Z', '+00:00'))
                    days = (hired - applied).days
                    if days > 0: time_to_hire.append(days)
                except: pass
        avg_time_to_hire = sum(time_to_hire) / len(time_to_hire) if time_to_hire else 0
        
        # Bias detection - optimization: only query resumes needed
        resume_ids = list(set([ObjectId(a["resume_id"]) for a in applications if a.get("resume_id")]))
        resumes = await db.resumes.find({"_id": {"$in": resume_ids}, "bias.has_bias": True}).to_list(length=len(resume_ids))
        bias_count = len(resumes)
        
        # Calculate rates for frontend KPIs
        active_jobs = len([j for j in jobs if j.get("status", "open").lower() in ["open", "published", "active"]])
        avg_applications_per_job = round(total_applications / total_jobs, 1) if total_jobs > 0 else 0
        interview_rate_pct = round((total_interviews / total_applications) * 100, 1) if total_applications > 0 else 0
        hire_rate_pct = round((total_hired / total_interviews) * 100, 1) if total_interviews > 0 else 0
        
        application_rate = (total_applications / total_jobs) if total_jobs > 0 else 0
        interview_rate = (total_interviews / total_applications) if total_applications > 0 else 0
        hire_rate = (total_hired / total_interviews) if total_interviews > 0 else 0
        
        status_counts = {}
        for app in applications:
            status = app.get("status", "New")
            status_counts[status] = status_counts.get(status, 0) + 1

        return {
            "kpis": {
                "total_jobs": total_jobs, "active_jobs": active_jobs,
                "total_applications": total_applications, "avg_applications_per_job": avg_applications_per_job,
                "total_candidates_interviewed": total_interviews, "interview_rate": interview_rate_pct,
                "total_hired": total_hired, "hire_rate": hire_rate_pct
            },
            "status_distribution": status_counts,
            "chart_data": {"labels": list(status_counts.keys()), "values": list(status_counts.values())},
            "average_match_score": round(avg_match_score, 2),
            "time_to_hire_days": round(avg_time_to_hire, 1),
            "bias_detection_count": bias_count,
            "application_rate": round(application_rate, 2),
            "interview_rate": round(interview_rate, 2),
            "hire_rate": round(hire_rate, 2)
        }
    except Exception as e:
        logger.error(f"Error calculating analytics summary: {e}")
        return {}


async def get_analytics_trends(recruiter_id: str, days: int = 30, db = None) -> Dict:
    """Get historical trends for analytics (Async)"""
    try:
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)
        
        MAX_QUERY_TIME_MS = 5000
        jobs = await db.jds.find({
            "recruiter_id": recruiter_id,
            "created_at": {"$gte": start_date.isoformat()},
            "is_deleted": {"$ne": True}
        }).max_time_ms(MAX_QUERY_TIME_MS).to_list(length=1000)
        
        job_ids = [str(job["_id"]) for job in jobs]
        
        applications = await db.applications.find({
            "job_id": {"$in": job_ids},
            "applied_at": {"$gte": start_date.isoformat()}
        }).to_list(length=5000)
        
        daily_data = {}
        current = start_date
        while current <= end_date:
            date_str = current.date().isoformat()
            daily_data[date_str] = {"date": date_str, "jobs_created": 0, "applications": 0, "interviews": 0, "hired": 0}
            current += timedelta(days=1)
        
        for job in jobs:
            try:
                job_date = datetime.fromisoformat(job.get("created_at", "").replace('Z', '+00:00')).date().isoformat()
                if job_date in daily_data: daily_data[job_date]["jobs_created"] += 1
            except: pass
        
        for app in applications:
            try:
                app_date = datetime.fromisoformat(app.get("applied_at", "").replace('Z', '+00:00')).date().isoformat()
                if app_date in daily_data:
                    daily_data[app_date]["applications"] += 1
                    if app.get("status") == "Interview": daily_data[app_date]["interviews"] += 1
                    elif app.get("status") == "Hired": daily_data[app_date]["hired"] += 1
            except: pass
        
        return {
            "period_days": days, "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
            "trends": list(daily_data.values())
        }
    except Exception as e:
        logger.error(f"Error calculating trends: {e}")
        return {"trends": []}


async def generate_report_data(recruiter_id: str, report_type: str = "summary", db = None) -> Dict:
    """Generate data for exportable reports (Async)"""
    try:
        summary = await get_analytics_summary(recruiter_id, db)
        trends = await get_analytics_trends(recruiter_id, 30, db)
        
        jobs = await db.jds.find({"recruiter_id": recruiter_id}).to_list(length=1000)
        job_ids = [str(job["_id"]) for job in jobs]
        applications = await db.applications.find({"job_id": {"$in": job_ids}}).to_list(length=5000)
        
        job_performance = []
        for job in jobs:
            job_apps = [a for a in applications if a.get("job_id") == str(job["_id"])]
            job_performance.append({
                "job_id": str(job["_id"]), "title": job.get("title", "Untitled"),
                "applications": len(job_apps),
                "hired": len([a for a in job_apps if a.get("status") == "Hired"]),
                "avg_match_score": sum([a.get("ai_match_score", 0) for a in job_apps]) / len(job_apps) if job_apps else 0
            })
        job_performance.sort(key=lambda x: x["applications"], reverse=True)
        
        return {
            "summary": summary, "trends": trends, "top_jobs": job_performance[:10],
            "generated_at": datetime.now(timezone.utc).isoformat(), "report_type": report_type
        }
    except Exception as e:
        logger.error(f"Error generating report data: {e}")
        return {}


async def generate_candidate_profile(interview_id: str, db) -> Dict:
    """Generate detailed profile for a single interview (Async)"""
    try:
        interview = await db.interviews.find_one({"_id": ObjectId(interview_id)})
        if not interview: return {}

        responses = interview.get("responses", [])
        response_times = []
        current_start = None
        if interview.get("started_at"):
             try: current_start = datetime.fromisoformat(interview["started_at"].replace('Z', '+00:00'))
             except: pass
        
        total_duration = 0
        for idx, resp in enumerate(responses):
            try:
                submitted_at_str = resp.get("timestamp")
                if not submitted_at_str: continue
                submitted_at = datetime.fromisoformat(submitted_at_str.replace('Z', '+00:00'))
                
                if current_start:
                    duration = (submitted_at - current_start).total_seconds()
                    if duration > 0:
                        response_times.append({
                            "question_index": idx, "duration_seconds": round(duration, 1),
                            "score": interview.get("scores", [])[idx]["score"] if idx < len(interview.get("scores", [])) else 0
                        })
                        total_duration += duration
                current_start = submitted_at
            except Exception as e:
                logger.warning(f"Error calculating time for q{idx}: {e}")
                continue

        durations = [r["duration_seconds"] for r in response_times]
        avg_time = sum(durations) / len(durations) if durations else 0
        
        total_violations = interview.get("total_strikes", 0)
        violations_array = interview.get("proctoring_violations", [])
        integrity_score = max(0, 100 - (total_violations * 10))
        
        violation_breakdown = {}
        violation_timeline = []
        
        for v in violations_array:
            v_type = v.get("type", "UNKNOWN")
            violation_breakdown[v_type] = violation_breakdown.get(v_type, 0) + 1
            violation_timeline.append({
                "type": v_type, "label": v.get("message", {}).get("title", v_type.replace("_", " ").title()),
                "timestamp": v.get("timestamp"), "severity": v.get("severity", "WARNING"),
                "question_number": v.get("question_index", "?")
            })

        final_score = interview.get("final_score", 0)
        return {
            "integrity_metrics": {
                "integrity_score": integrity_score, "total_violations": total_violations,
                "violation_breakdown": violation_breakdown, "violation_timeline": violation_timeline
            },
            "performance_metrics": {
                "overall_score": {"value": round(final_score, 1), "percentile": 0},
                "category_scores": {"Overall": {"score": final_score}}
            },
            "time_analytics": {
                "avg_time_per_question": round(avg_time, 1), "total_duration": round(total_duration, 1),
                "details": response_times
            }
        }
    except Exception as e:
        logger.error(f"Error generating candidate profile: {e}")
        return {}
