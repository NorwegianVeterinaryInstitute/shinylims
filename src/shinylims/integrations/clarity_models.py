"""
Minimal SQLAlchemy models for the Clarity Postgres sequencing prototype.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base declarative model for Clarity Postgres tables and views."""


class Process(Base):
    __tablename__ = "process"

    processid: Mapped[int] = mapped_column(Integer, primary_key=True)
    luid: Mapped[str | None] = mapped_column(String)
    daterun: Mapped[datetime | None] = mapped_column(DateTime)
    workstatus: Mapped[str | None] = mapped_column(String)
    techid: Mapped[int | None] = mapped_column(ForeignKey("principals.principalid"))
    typeid: Mapped[int | None] = mapped_column(Integer)


class ProcessIOTracker(Base):
    __tablename__ = "processiotracker"

    trackerid: Mapped[int] = mapped_column(Integer, primary_key=True)
    processid: Mapped[int | None] = mapped_column(ForeignKey("process.processid"))
    inputartifactid: Mapped[int | None] = mapped_column(ForeignKey("artifact.artifactid"))


class OutputMapping(Base):
    __tablename__ = "outputmapping"

    mappingid: Mapped[int] = mapped_column(Integer, primary_key=True)
    trackerid: Mapped[int | None] = mapped_column(ForeignKey("processiotracker.trackerid"))
    outputartifactid: Mapped[int | None] = mapped_column(ForeignKey("artifact.artifactid"))


class ResultFile(Base):
    __tablename__ = "resultfile"

    artifactid: Mapped[int] = mapped_column(ForeignKey("artifact.artifactid"), primary_key=True)


class Artifact(Base):
    __tablename__ = "artifact"

    artifactid: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str | None] = mapped_column(String)
    isoriginal: Mapped[bool | None] = mapped_column(Boolean)


class ArtifactUdfView(Base):
    __tablename__ = "artifact_udf_view"

    artifactid: Mapped[int] = mapped_column(ForeignKey("artifact.artifactid"), primary_key=True)
    udtname: Mapped[str] = mapped_column(String, primary_key=True)
    udfname: Mapped[str] = mapped_column(String, primary_key=True)
    udftype: Mapped[str] = mapped_column(String, primary_key=True)
    udfvalue: Mapped[str] = mapped_column(String, primary_key=True)
    udfunitlabel: Mapped[str] = mapped_column(String, primary_key=True)


class ProcessUdfView(Base):
    __tablename__ = "process_udf_view"

    processid: Mapped[int] = mapped_column(ForeignKey("process.processid"), primary_key=True)
    typeid: Mapped[int] = mapped_column(Integer, primary_key=True)
    udtname: Mapped[str] = mapped_column(String, primary_key=True)
    udfname: Mapped[str] = mapped_column(String, primary_key=True)
    udftype: Mapped[str] = mapped_column(String, primary_key=True)
    udfvalue: Mapped[str] = mapped_column(String, primary_key=True)
    udfunitlabel: Mapped[str] = mapped_column(String, primary_key=True)


class Sample(Base):
    __tablename__ = "sample"

    processid: Mapped[int] = mapped_column(ForeignKey("process.processid"), primary_key=True)
    sampleid: Mapped[int | None] = mapped_column(Integer)
    projectid: Mapped[int | None] = mapped_column(ForeignKey("project.projectid"))
    name: Mapped[str | None] = mapped_column(String)
    datereceived: Mapped[datetime | None] = mapped_column(DateTime)
    controltypeid: Mapped[int | None] = mapped_column(Integer)


class SampleUdfView(Base):
    __tablename__ = "sample_udf_view"

    sampleid: Mapped[int] = mapped_column(Integer, primary_key=True)
    udtname: Mapped[str] = mapped_column(String, primary_key=True)
    udfname: Mapped[str] = mapped_column(String, primary_key=True)
    udftype: Mapped[str] = mapped_column(String, primary_key=True)
    udfvalue: Mapped[str] = mapped_column(String, primary_key=True)
    udfunitlabel: Mapped[str] = mapped_column(String, primary_key=True)


class ArtifactSampleMap(Base):
    __tablename__ = "artifact_sample_map"

    artifactid: Mapped[int] = mapped_column(ForeignKey("artifact.artifactid"), primary_key=True)
    processid: Mapped[int] = mapped_column(ForeignKey("sample.processid"), primary_key=True)


class ArtifactLabelMap(Base):
    __tablename__ = "artifact_label_map"

    artifactid: Mapped[int] = mapped_column(ForeignKey("artifact.artifactid"), primary_key=True)
    labelid: Mapped[int] = mapped_column(ForeignKey("reagentlabel.labelid"), primary_key=True)


class ReagentLabel(Base):
    __tablename__ = "reagentlabel"

    labelid: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str | None] = mapped_column(String)


class Analyte(Base):
    __tablename__ = "analyte"

    artifactid: Mapped[int] = mapped_column(ForeignKey("artifact.artifactid"), primary_key=True)


class Container(Base):
    __tablename__ = "container"

    containerid: Mapped[int] = mapped_column(Integer, primary_key=True)
    createddate: Mapped[datetime | None] = mapped_column(DateTime)
    lastmodifieddate: Mapped[datetime | None] = mapped_column(DateTime)
    name: Mapped[str | None] = mapped_column(String)
    stateid: Mapped[int | None] = mapped_column(Integer)
    typeid: Mapped[int | None] = mapped_column(ForeignKey("containertype.typeid"))


class ContainerType(Base):
    __tablename__ = "containertype"

    typeid: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str | None] = mapped_column(String)


class ContainerPlacement(Base):
    __tablename__ = "containerplacement"

    placementid: Mapped[int] = mapped_column(Integer, primary_key=True)
    processartifactid: Mapped[int | None] = mapped_column(ForeignKey("artifact.artifactid"))
    containerid: Mapped[int | None] = mapped_column(ForeignKey("container.containerid"))
    wellxposition: Mapped[int | None] = mapped_column(Integer)
    wellyposition: Mapped[int | None] = mapped_column(Integer)


class Project(Base):
    __tablename__ = "project"

    projectid: Mapped[int] = mapped_column(Integer, primary_key=True)
    luid: Mapped[str | None] = mapped_column(String)
    name: Mapped[str | None] = mapped_column(String)
    opendate: Mapped[datetime | None] = mapped_column(DateTime)
    closedate: Mapped[datetime | None] = mapped_column(DateTime)
    researcherid: Mapped[int | None] = mapped_column(ForeignKey("researcher.researcherid"))


class EntityUdfView(Base):
    __tablename__ = "entity_udf_view"

    attachtoid: Mapped[int] = mapped_column(Integer, primary_key=True)
    attachtoclassid: Mapped[int] = mapped_column(Integer, primary_key=True)
    udtname: Mapped[str] = mapped_column(String, primary_key=True)
    udfname: Mapped[str] = mapped_column(String, primary_key=True)
    udftype: Mapped[str] = mapped_column(String, primary_key=True)
    udfvalue: Mapped[str] = mapped_column(String, primary_key=True)
    udfunitlabel: Mapped[str] = mapped_column(String, primary_key=True)


class Principals(Base):
    __tablename__ = "principals"

    principalid: Mapped[int] = mapped_column(Integer, primary_key=True)
    researcherid: Mapped[int | None] = mapped_column(ForeignKey("researcher.researcherid"))


class Researcher(Base):
    __tablename__ = "researcher"

    researcherid: Mapped[int] = mapped_column(Integer, primary_key=True)
    firstname: Mapped[str | None] = mapped_column(String)
    lastname: Mapped[str | None] = mapped_column(String)
    labid: Mapped[int | None] = mapped_column(ForeignKey("lab.labid"))


class Lab(Base):
    __tablename__ = "lab"

    labid: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str | None] = mapped_column(String)
