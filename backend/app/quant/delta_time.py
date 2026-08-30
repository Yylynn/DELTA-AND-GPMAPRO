"""Causal, skill-style 118 trading-bar DELTA/ITD structure."""
from __future__ import annotations
from datetime import date, timedelta
from enum import Enum
import statistics
import pandas as pd
from pydantic import BaseModel, Field

ITD_TRADING_BARS, ITD_CALENDAR_DAYS, DEFAULT_N, MIN_GAP_TRADING_DAYS = 118, 171.0, 12, 8
COLOR_PHASE_DAYS, MIN_RECOMMENDED_BARS, MIN_HISTORY_CALENDAR_DAYS = ITD_CALENDAR_DAYS / 4, 756, 118
SUPPORTED_SEQUENCE_LENGTHS = range(12, 13)
PHASE_NAMES = ("ORANGE", "GREEN", "RED", "BLUE")
class DeltaEventType(str, Enum): HIGH="HIGH"; LOW="LOW"
class SequenceLengthMode(str, Enum): FIXED="fixed"; AUTO="auto"; MANUAL="manual"
class ITDConfig(BaseModel):
    sequence_length_mode: SequenceLengthMode = SequenceLengthMode.FIXED
    fixed_n: int = Field(default=12, ge=12, le=12)
    manual_n: int | None = Field(default=None, ge=12, le=12)
    candidate_half_window_days: float = Field(default=7, gt=0, le=30)
    reversal_enabled: bool = True
    reversal_swing_left: int = Field(default=2, ge=1, le=10)
    reversal_swing_right: int = Field(default=2, ge=1, le=10)
    reversal_atr_period: int = Field(default=14, ge=2, le=100)
    reversal_min_excursion_atr: float = Field(default=1.0, gt=0, le=10)
    reversal_ai_enabled: bool = True
    reversal_ai_threshold: float = Field(default=.80, ge=0, le=1)
class DeltaWindow(BaseModel):
    event_id: str; event_type: DeltaEventType; cycle_type: str; anchor_date: date; expected_date: date; window_start: date; window_end: date; tolerance_days: int=Field(ge=0); confidence: float=Field(ge=0,le=1); source: str; metadata: dict={}
class ManualDeltaEngine:
    def __init__(self,events:list[dict]): self.events=events
    def windows(self):
        out=[]
        for x in self.events:
            e=date.fromisoformat(str(x["expected_date"])); t=int(x.get("tolerance_days",0)); pub=str(x.get("published_at") or x["anchor_date"])
            out.append(DeltaWindow(event_id=str(x["event_id"]),event_type=x["event_type"],cycle_type=x.get("cycle_type","MANUAL"),anchor_date=date.fromisoformat(str(x["anchor_date"])),expected_date=e,window_start=e-timedelta(days=t),window_end=e+timedelta(days=t),tolerance_days=t,confidence=float(x.get("confidence",1)),source="manual",metadata={**x.get("metadata",{}),"published_at":pub}))
        return out
class ConfigurableDeltaEngine(ManualDeltaEngine):
    @classmethod
    def from_config(cls,config:dict): return cls(config.get("events",[]))
def _day(x): return pd.Timestamp(x).date()
def _phase(i): return PHASE_NAMES[i%4]


def _annotate_adjacent_window_conflicts(predictions: list[dict], boundary: dict | None) -> list[dict]:
    """Add display-only dependency state without changing statistical windows.

    DELTA's per-point standard-deviation ranges are independent estimates, so
    adjacent ranges can overlap.  The overlap is useful uncertainty evidence,
    not a reason to move either date.  Only the prediction immediately after
    an unresolved live boundary becomes conditional on that boundary's
    confirmation.
    """
    for index, prediction in enumerate(predictions):
        prediction.update({
            "overlaps_previous_window": False,
            "overlap_start": None,
            "overlap_end": None,
            "previous_number": None,
            "requires_previous_confirmation": False,
            "conditional": False,
            "independent_window_eligible": True,
        })
        if index == 0:
            continue
        previous = predictions[index - 1]
        start = max(_day(prediction["window_start"]), _day(previous["window_start"]))
        end = min(_day(prediction["window_end"]), _day(previous["window_end"]))
        if start > end:
            continue
        requires_confirmation = (
            index == 1
            and previous.get("phase") == "current_candidate"
            and not bool((boundary or {}).get("confirmed"))
        )
        prediction.update({
            "overlaps_previous_window": True,
            "overlap_start": start.isoformat(),
            "overlap_end": end.isoformat(),
            "previous_number": previous["number"],
            "requires_previous_confirmation": requires_confirmation,
            "conditional": requires_confirmation,
            "independent_window_eligible": not requires_confirmation,
        })
    return predictions


def fixed_cycle_grid(anchor_dates,display_dates):
    if not anchor_dates or not display_dates:return []
    out=[]
    for i in range(0,len(anchor_dates),ITD_TRADING_BARS//4):
        a=anchor_dates[i]; visible=[d for d in display_dates if d<=a]
        out.append({"id":f"itd-phase-{i}","anchor_date":a.isoformat(),"calendar_date":a.isoformat(),"display_date":(visible[-1] if visible else display_dates[0]).isoformat(),"color":_phase(i//(ITD_TRADING_BARS//4)),"phase_index":(i//(ITD_TRADING_BARS//4))%4,"cycle":i//ITD_TRADING_BARS+1,"source_bar_index":i,"is_future":False})
    return out
def lunar_grid(start,end,trading_dates,future_lines=8): return fixed_cycle_grid(trading_dates,trading_dates)
REVERSAL_NORMAL = "NORMAL"
REVERSAL_OPEN = "ITW_OPEN"
REVERSAL_CONFIRMED = "INVERSION_CONFIRMED"
REVERSAL_DOUBLE = "DOUBLE_INVERSION_CONFIRMED"
REVERSAL_CLOSED = "ITW_CLOSED"

def _atr(data: pd.DataFrame, period: int) -> pd.Series:
    previous = data["close"].shift(1)
    true_range = pd.concat([(data["high"] - data["low"]).abs(), (data["high"] - previous).abs(), (data["low"] - previous).abs()], axis=1).max(axis=1)
    return true_range.rolling(period, min_periods=1).mean()

def _swing_candidates(data: pd.DataFrame, left: int, right: int) -> list[dict]:
    """Return only pivots that were knowable after ``right`` additional bars."""
    out = []
    for index in range(left, len(data) - right):
        lo, hi = index - left, index + right + 1
        if float(data.high.iloc[index]) == float(data.high.iloc[lo:hi].max()):
            out.append({"bar_index": index, "type": "HIGH", "price": float(data.high.iloc[index]), "confirmed_index": index + right})
        if float(data.low.iloc[index]) == float(data.low.iloc[lo:hi].min()):
            out.append({"bar_index": index, "type": "LOW", "price": float(data.low.iloc[index]), "confirmed_index": index + right})
    return out

def _reversal_ai_score(data: pd.DataFrame, atr: pd.Series, candidate: dict | None) -> dict:
    """Transparent probability proxy until labelled inversion data exists.

    This deliberately is not a black-box prediction.  It exposes each input
    so a later trained classifier can keep the same response contract.
    """
    index = candidate["bar_index"] if candidate else len(data) - 1
    current_atr = max(float(atr.iloc[index]), 1e-9)
    start = max(0, index - 20)
    trend = abs(float(data.close.iloc[index]) - float(data.close.iloc[start])) / (current_atr * max(1, index - start))
    volume_mean = float(data.volume.iloc[start:index + 1].mean()) or 1.0
    volume_ratio = float(data.volume.iloc[index]) / volume_mean
    excursion_atr = abs(candidate["price"] - candidate["prior_price"]) / current_atr if candidate else 0.0
    probability = min(.95, .15 + min(.35, excursion_atr * .20) + min(.20, trend * .20) + min(.15, volume_ratio * .05))
    return {"model": "AUDITABLE_HEURISTIC_V1", "available": True, "probability": round(probability, 4), "features": {"excursion_atr": round(excursion_atr, 4), "trend_atr_per_bar": round(trend, 4), "volume_ratio": round(volume_ratio, 4)}}

class ITDDeltaEngine:
    def __init__(self,config=None): self.config=config or ITDConfig()
    @staticmethod
    def _unit(data,base,count,start_high,previous):
        """Extract only the numbered bands which have actually begun.

        The old live-unit implementation divided *the available tail* into
        twelve pieces.  That fabricated #9–#12 from an 8-band tail, making
        every stock appear to be on #12 and therefore forecast #1.  Bands are
        instead always positioned in the immutable 118-bar template; the
        last, partially elapsed band is the current boundary.
        """
        seg=data.iloc[base:base+count].reset_index(drop=True); out=[]; high=start_high
        for phase in range(4):
            a,b=round(phase*ITD_TRADING_BARS/4),round((phase+1)*ITD_TRADING_BARS/4)
            if a >= len(seg): break
            b=min(b,len(seg)); sub=seg.iloc[a:b]
            for slot in range(3):
                nominal_lo=round(slot*(ITD_TRADING_BARS/4)/3)
                nominal_hi=round((slot+1)*(ITD_TRADING_BARS/4)/3)
                lo,hi=nominal_lo,min(nominal_hi,len(sub))
                if lo >= len(sub): break
                # ``seg`` is local to this unit while ``bar_index`` is global.
                # Convert the previous global boundary before slicing it.
                prior_local=(out[-1]["bar_index"] if out else previous)-base
                start=max(a+lo,prior_local+MIN_GAP_TRADING_DAYS); end=a+hi
                # Never relax the spacing rule.  If a live band cannot host
                # the next legal turn, that number remains a future forecast.
                if end<=start: return out
                choices=seg.iloc[start:end]
                if choices.empty:continue
                idx=int(choices["high"].astype(float).idxmax() if high else choices["low"].astype(float).idxmin()); row=seg.iloc[idx]
                out.append({"bar_index":base+idx,"type":"HIGH" if high else "LOW","price":float(row["high"] if high else row["low"]),"phase_index":phase}); high=not high
        return out
    @staticmethod
    def _earliest_trading_date(anchor_date, trading_dates):
        """Return the first date at least eight trading sessions after anchor."""
        anchor = _day(anchor_date)
        positions = [index for index, value in enumerate(trading_dates) if value == anchor]
        if positions and positions[0] + MIN_GAP_TRADING_DAYS < len(trading_dates):
            return trading_dates[positions[0] + MIN_GAP_TRADING_DAYS]
        return (pd.Timestamp(anchor) + pd.offsets.BDay(MIN_GAP_TRADING_DAYS)).date()
    @classmethod
    def _constrain_window(cls, anchor_date, expected, lo, hi, trading_dates):
        earliest = cls._earliest_trading_date(anchor_date, trading_dates)
        if expected >= earliest:
            return expected, lo, hi, False, earliest
        shift = earliest - expected
        return earliest, lo + shift, hi + shift, True, earliest
    @staticmethod
    def _forecast(anchor, history, as_of, trading_dates, steps=2):
        """Forecast from this stock's current boundary and its own history."""
        if not anchor:return []
        gaps={i:[] for i in range(1,13)}
        for a,b in zip(history,history[1:]):gaps[b["number"]].append((_day(b["date"])-_day(a["date"])).days)
        d=_day(anchor["date"]); num=anchor["number"]; typ=anchor["type"]; out=[]
        # Walk through any already elapsed transitions before exposing the
        # next two events.  A stale #4/#5 forecast must never remain drawn
        # inside the realised K-line history.
        for _ in range(48):
            target=num%12+1; sample=gaps[target]; mean=statistics.mean(sample) if sample else ITD_CALENDAR_DAYS/12; std=statistics.stdev(sample) if len(sample)>=2 else max(mean*.2,ITD_CALENDAR_DAYS/12*.3); expected=d+timedelta(days=round(mean)); lo,hi=expected-timedelta(days=round(std)),expected+timedelta(days=round(std)); expected,lo,hi,constrained,earliest=ITDDeltaEngine._constrain_window(d,expected,lo,hi,trading_dates); typ="LOW" if typ=="HIGH" else "HIGH"
            if expected > as_of:
                step=len(out)+1
                out.append({"id":f"itd-future-{target}-{step}","number":target,"type":typ,"phase":"predicted","historical":False,"anchor_date":d.isoformat(),"expected_date":expected.isoformat(),"date_range":[lo.isoformat(),hi.isoformat()],"window_start":lo.isoformat(),"window_end":hi.isoformat(),"lo_date":lo.isoformat(),"hi_date":hi.isoformat(),"gap_mean_days":round(mean,2),"gap_std_days":round(std,2),"sample_count":len(sample),"min_gap_trading_days":MIN_GAP_TRADING_DAYS,"min_gap_earliest_date":earliest.isoformat(),"constraint_applied":constrained,"confidence":round(min(.9,.35+.08*len(sample)),2)})
                if len(out) == steps: break
            d,num=expected,target
        return out
    @staticmethod
    def _current_boundary_prediction(boundary, history, trading_dates):
        """Represent the unconfirmed live boundary as the first prediction.

        A candidate #5 is observable in price but is not confirmed yet.  It
        must therefore remain the current prediction, rather than being
        consumed and making #6 look like the next event.
        """
        if not boundary:
            return None
        gaps = []
        for left, right in zip(history, history[1:]):
            if right["number"] == boundary["number"]:
                gaps.append((_day(right["date"]) - _day(left["date"])).days)
        mean = statistics.mean(gaps) if gaps else ITD_CALENDAR_DAYS / 12
        std = statistics.stdev(gaps) if len(gaps) >= 2 else max(mean * .2, ITD_CALENDAR_DAYS / 12 * .3)
        # The time window is calculated from the last confirmed predecessor;
        # the chart marker itself remains at the candidate's observed OHLC.
        predecessor = history[-1] if history else boundary
        anchor_date = _day(predecessor["date"])
        expected = anchor_date + timedelta(days=round(mean))
        lo, hi = expected - timedelta(days=round(std)), expected + timedelta(days=round(std))
        expected, lo, hi, constrained, earliest = ITDDeltaEngine._constrain_window(anchor_date, expected, lo, hi, trading_dates)
        # The yellow boundary is an observed but unconfirmed live turn.  Once
        # it forms after its original statistical window, keep the same window
        # width but re-centre it on this stock's actual boundary date.  Without
        # this, a fresh #5 could still display last week's stale forecast.
        observed_date = _day(boundary["date"])
        rebased_to_boundary = observed_date > hi
        if rebased_to_boundary:
            shift = observed_date - expected
            expected, lo, hi = observed_date, lo + shift, hi + shift
        return {
            "id": f"itd-current-{boundary['id']}", "number": boundary["number"],
            "type": boundary["type"], "phase": "current_candidate", "historical": False,
            "anchor_date": anchor_date.isoformat(), "expected_date": expected.isoformat(), "date_range": [lo.isoformat(), hi.isoformat()],
            "window_start": lo.isoformat(), "window_end": hi.isoformat(),
            "lo_date": lo.isoformat(), "hi_date": hi.isoformat(),
            "gap_mean_days": round(mean, 2), "gap_std_days": round(std, 2),
            "sample_count": len(gaps), "min_gap_trading_days": MIN_GAP_TRADING_DAYS,
            "min_gap_earliest_date": earliest.isoformat(), "constraint_applied": constrained,
            "candidate_window_rebased": rebased_to_boundary,
            "confidence": round(min(.9, .35 + .08 * len(gaps)), 2),
            "observed_boundary_date": boundary["date"],
        }
    def _apply_reversals(self, data: pd.DataFrame, points: list[dict], dates: list[date]) -> dict:
        """Detect causal IBPs in each M -> 1 -> 2 window and apply their mapping.

        The time/number grid remains immutable.  An inversion changes only a
        point's HIGH/LOW role after the IBP becomes confirmed, never the grid
        date itself.  This keeps prefix replays causal: a prefix cannot see an
        IBP whose right-hand swing confirmation bar has not yet arrived.
        """
        empty = {"state": REVERSAL_NORMAL, "itw_active": False, "window": [12, 1, 2], "windows": [], "ibps": [], "candidates": [], "effective_mapping": {}, "state_history": [], "ai": {"available": self.config.reversal_ai_enabled, "threshold": self.config.reversal_ai_threshold}}
        if not self.config.reversal_enabled or len(points) < 3:
            return empty
        atr = _atr(data, self.config.reversal_atr_period)
        swings = _swing_candidates(data, self.config.reversal_swing_left, self.config.reversal_swing_right)
        windows, all_ibps, all_candidates, states = [], [], [], []
        # A numbered point is represented once per 118-bar unit.  Only a
        # completed M/1/2 boundary can be closed; a live one stays ITW_OPEN.
        by_cycle = {}
        for point in points:
            by_cycle.setdefault(point["cycle"], {})[point["number"]] = point
            point["base_type"] = point["type"]
            point["reversal_effective_on"] = None
        for cycle, unit in sorted(by_cycle.items()):
            previous = by_cycle.get(cycle - 1, {})
            m, one, two = previous.get(12), unit.get(1), unit.get(2)
            if not m or not one:
                continue
            end = two["bar_index"] if two else len(data) - 1
            candidates: list[dict] = []
            # M' is a same-role swing as the normally expected #1, but before
            # #1's time slot.  1' is similarly a #2-role swing before #2.
            phases = (("M'", m, one, m["bar_index"], one["bar_index"]),)
            if two:
                phases += (("1'", one, two, one["bar_index"], two["bar_index"]),)
            for label, prior, expected, start, finish in phases:
                matches = [candidate for candidate in swings if start < candidate["bar_index"] < finish and candidate["type"] == expected["base_type"]]
                if not matches:
                    continue
                # Pick the most meaningful excursion, not merely the first
                # small local wiggle.  The ATR is sampled at the candidate.
                candidate = max(matches, key=lambda value: abs(value["price"] - prior["price"]))
                threshold = float(atr.iloc[candidate["bar_index"]]) * self.config.reversal_min_excursion_atr
                excursion = abs(candidate["price"] - prior["price"])
                if excursion < threshold:
                    continue
                confirmed_index = candidate["confirmed_index"]
                if confirmed_index >= len(dates):
                    continue
                score_input = {**candidate, "prior_price": prior["price"]}
                ai = _reversal_ai_score(data, atr, score_input) if self.config.reversal_ai_enabled else {"model": "DISABLED", "available": False, "probability": None, "features": {}}
                item = {"id": f"itd-ibp-{cycle}-{label.replace(chr(39), 'prime')}", "label": label, "cycle": cycle, "type": candidate["type"], "date": dates[candidate["bar_index"]].isoformat(), "actual_date": dates[candidate["bar_index"]].isoformat(), "price": candidate["price"], "bar_index": candidate["bar_index"], "confirmed_on": dates[confirmed_index].isoformat(), "tradable_on": dates[confirmed_index + 1].isoformat() if confirmed_index + 1 < len(dates) else None, "excursion": round(excursion, 6), "atr": round(float(atr.iloc[candidate["bar_index"]]), 6), "threshold": round(threshold, 6), "ai": ai, "ai_gate_passed": bool(ai["available"] and ai["probability"] >= self.config.reversal_ai_threshold)}
                candidates.append(item)
            candidates.sort(key=lambda value: value["bar_index"])
            accepted = [item for item in candidates if item["ai_gate_passed"]][:2]
            # A single IBP flips the mapping after its location.  Two IBPs
            # restore it after the second point, exactly as the theory's
            # double inversion example specifies.
            for ordinal, ibp in enumerate(accepted, start=1):
                ibp["ordinal"] = ordinal
                flip_from = one if ibp["label"] == "M'" else two
                if not flip_from:
                    continue
                should_flip = ordinal == 1
                for point in points:
                    if point["cycle"] < cycle or (point["cycle"] == cycle and point["bar_index"] < flip_from["bar_index"]):
                        continue
                    if should_flip:
                        point["type"] = "LOW" if point["base_type"] == "HIGH" else "HIGH"
                    else:
                        point["type"] = point["base_type"]
                    point["reversal_effective_on"] = ibp["confirmed_on"]
                states.append({"cycle": cycle, "state": REVERSAL_CONFIRMED if ordinal == 1 else REVERSAL_DOUBLE, "effective_on": ibp["confirmed_on"], "ibp_id": ibp["id"]})
            state = REVERSAL_OPEN
            if len(accepted) == 1:
                state = REVERSAL_CONFIRMED
            elif len(accepted) >= 2:
                state = REVERSAL_DOUBLE
            max_probability = max((item["ai"]["probability"] or 0 for item in candidates), default=0)
            if not accepted and max_probability >= self.config.reversal_ai_threshold:
                state = "AI_WATCH"
            elif not accepted and not two:
                state = "ITW_WATCH"
            # Completed windows with no approved IBP are deliberately omitted
            # from the user-facing list: normal alternation is the baseline,
            # not a reversal event.
            window = {"id": f"itw-{cycle}", "cycle": cycle, "state": state, "window_start": m["date"], "window_end": two["date"] if two else dates[-1].isoformat(), "m_date": m["date"], "one_date": one["date"], "two_date": two["date"] if two else None, "ibp_ids": [item["id"] for item in accepted], "candidate_ids": [item["id"] for item in candidates], "closed": two is not None, "ai_probability": round(max_probability, 4)}
            if not two or accepted or state == "AI_WATCH":
                windows.append(window)
            all_ibps.extend(accepted); all_candidates.extend(candidates)
        latest = windows[-1] if windows else None
        return {"state": latest["state"] if latest else REVERSAL_NORMAL, "itw_active": bool(latest and not latest["closed"]), "window": [12, 1, 2], "windows": windows, "ibps": all_ibps, "candidates": all_candidates, "effective_mapping": {point["id"]: point["type"] for point in points}, "state_history": states, "ai": {"available": self.config.reversal_ai_enabled, "threshold": self.config.reversal_ai_threshold}}
    def analyze(self,frame):
        need={"date","open","high","low","close","volume"}
        if not need.issubset(frame.columns):raise ValueError("ITD requires date, open, high, low, close and volume")
        data=frame.copy().sort_values("date").reset_index(drop=True); data["date"]=pd.to_datetime(data.date); dates=[_day(x) for x in data.date]; span=(dates[-1]-dates[0]).days+1 if dates else 0
        base={"model":"Skill DELTA ITD","sequence_length":12,"sequence_length_mode":"fixed","itd_calendar_days":ITD_CALENDAR_DAYS,"color_phase_days":COLOR_PHASE_DAYS,"min_gap_trading_days":MIN_GAP_TRADING_DAYS,"bar_count":len(data),"calendar_span_days":span,"required_calendar_days":MIN_HISTORY_CALENDAR_DAYS,"recommended_bars":MIN_RECOMMENDED_BARS}
        if len(data)<ITD_TRADING_BARS:return {**base,"status":"INSUFFICIENT_HISTORY","grid_lines":[],"cycle_boundaries":[],"points":[],"confirmed_points":[],"candidate_points":[],"boundary_point":None,"next_prediction":None,"future_predictions":[],"transition_table":[],"reversal":{"state":REVERSAL_NORMAL,"itw_active":False,"window":[12,1,2],"windows":[],"ibps":[],"effective_mapping":{},"state_history":[]}}
        raw=[]; high=True; prev=-999999; units=(len(data)+117)//118
        for cycle in range(units):
            start=cycle*118; count=min(118,len(data)-start)
            # The live tail only emits bands which both started and can honour
            # the global eight-trading-day spacing rule.
            pts=self._unit(data,start,count,high,prev)
            for j,p in enumerate(pts):
                p.update({"id":f"itd-{cycle+1}-{j+1}","number":j+1,"cycle":cycle+1,"date":dates[p["bar_index"]].isoformat(),"actual_date":dates[p["bar_index"]].isoformat(),"color_phase":_phase(p["phase_index"]),"historical":cycle<units-1,"phase":"historical" if cycle<units-1 else "candidate"}); high=p["type"]=="LOW"; prev=p["bar_index"]; raw.append(p)
        for p in raw:
            # Completed units are confirmed at the following unit boundary.
            # In the live unit, every completed band can be known after its
            # local confirmation delay; only its terminal point stays yellow
            # and becomes the first of the two forecasts.
            is_terminal = p is raw[-1]
            if p["historical"]:
                confirmed = dates[min(len(dates)-1, p["cycle"] * 118)].isoformat()
            elif not is_terminal and p["bar_index"] + 8 < len(dates):
                confirmed = dates[p["bar_index"] + 8].isoformat()
            else:
                confirmed = None
            p["confirmed_on"]=confirmed; ci=next((i for i,d in enumerate(dates) if confirmed and d.isoformat()==confirmed),None); p["tradable_on"]=dates[ci+1].isoformat() if ci is not None and ci+1<len(dates) else None; p["confirmed"]=(not is_terminal) and p["tradable_on"] is not None
        reversal = self._apply_reversals(data, raw, dates)
        confirmed=[p for p in raw if p["confirmed"]]
        # Historical transition samples use confirmed, stock-specific extrema;
        # the live boundary only supplies the starting number/date.
        current_prediction = self._current_boundary_prediction(raw[-1] if raw else None, confirmed, dates)
        following_predictions = self._forecast(raw[-1] if raw else None, confirmed, dates[-1], dates, steps=11)
        # The full table begins at the unresolved current boundary, then walks
        # forward one complete 1–12 sequence from that point.
        all_pred = ([current_prediction] if current_prediction else []) + following_predictions
        _annotate_adjacent_window_conflicts(all_pred, raw[-1] if raw else None)
        pred=all_pred[:2]
        table=[]
        for n in range(1,13):
            sample=[(_day(b["date"])-_day(a["date"])).days for a,b in zip(confirmed,confirmed[1:]) if b["number"]==n]
            next_occurrence=next((item for item in all_pred if item["number"] == n), None)
            table.append({"number":n,"sample_count":len(sample),"mean_days":round(statistics.mean(sample),2) if sample else None,"std_days":round(statistics.stdev(sample),2) if len(sample)>=2 else None,"last_interval_days":sample[-1] if sample else None,"prediction":next_occurrence})
        bounds=[{"id":f"itd-{i//118+1}","date":dates[i].isoformat(),"label":f"ITD{i//118+1}"} for i in range(0,len(dates),118)]
        return {**base,"status":"READY" if confirmed else "STRUCTURE_ONLY","sequence_label":"Skill DELTA ITD (118 bars, N=12)","complete_units":len(data)//118,"grid_lines":fixed_cycle_grid(dates,dates),"cycle_boundaries":bounds,"points":raw,"confirmed_points":confirmed,"candidate_points":[p for p in raw if not p["confirmed"]],"boundary_point":raw[-1] if raw else None,"next_prediction":pred[0] if pred else None,"future_predictions":pred,"transition_predictions":all_pred,"transition_table":table,"reversal":reversal,"history_confidence":"SUFFICIENT" if len(data)>=756 else "LIMITED"}
    def signal_windows(self,frame):
        a=self.analyze(frame); p=a.get("next_prediction"); pts=a.get("confirmed_points",[])
        if not p or not pts:return []
        reversal = a.get("reversal", {})
        return [{"event_id":p["id"],"event_type":p["type"],"cycle_type":"SKILL_ITD","anchor_date":pts[-1]["date"],"expected_date":p["expected_date"],"window_start":p["window_start"],"window_end":p["window_end"],"tolerance_days":0,"confidence":p["confidence"],"source":"skill-itd","metadata":{"number":p["number"],"phase":"predicted","reversal_state":reversal.get("state", REVERSAL_NORMAL),"reversal_effective_on":pts[-1].get("reversal_effective_on")}}]
    def events_for_signal(self,frame): return self.signal_windows(frame)
