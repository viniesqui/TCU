import asyncio
import logging
import sys

from src.agents.grading_agent import GradingAgent
from src.config import settings

def main():
    settings.max_cost_student = 1.00 # ensure we have budget
    agent = GradingAgent(max_cost=settings.max_cost_student)
    
    assignment_prompt = "Escribe un ensayo sobre microservicios."
    student_response = "Los microservicios permiten dividir una aplicación grande en servicios pequeños y escalables. Tienen ventajas en despliegue continuo."
    
    result = agent.grade_submission(assignment_prompt, student_response)
    print("Grade Result:", result)

if __name__ == "__main__":
    main()
